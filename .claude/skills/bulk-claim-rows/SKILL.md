---
name: bulk-claim-rows
description: One-shot sweep that tags every part / contract in the catalog with a project (#44) and/or claims them under an X-Actor identity (#54). Use when the user wants to "backfill the watchervault project tag", "claim all the unattributed rows", "retroactively tag every contract", or any "set X on everything" follow-up after registering a new project or after the X-Actor migration. Wraps `.claude/skills/bulk-claim-rows/scripts/bulk-claim-rows.sh`. Distinct from `/update-part` and `/update-contract`, which are the right tools for one-row edits.
---

# bulk-claim-rows

You are running a one-pass sweep over every part and contract in the
catalog, setting `project` and/or claiming `created_by_actor` on each
row that matches the filter. The mechanics — paging, filtering,
dry-run table, confirmation gate, summary — live in
`.claude/skills/bulk-claim-rows/scripts/bulk-claim-rows.sh`. Your
job is to figure out the right
flags with the user, run the script, and read the dry-run together
before approving.

## When to use this vs `/update-part` or `/update-contract`

- **One row, real edit** → `/update-part` or `/update-contract`. Body
  changes, version bumps with rationale, repo_uri renames, alias
  curation. The bulk script doesn't replace these.
- **Every row, mechanical metadata sweep** → this skill. Just landed
  a new project and need to tag the existing 30 rows; just adopted
  X-Actor and need to claim the legacy null-attributed rows.

## Server location

| Variable          | Required | Purpose                                                                  |
| ----------------- | -------- | ------------------------------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL. No trailing slash.                                             |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.                                     |
| `TITAN_TYR_ACTOR` | no       | Fallback for `--actor`. Convenient if the same identity claims everything. |

If `TITAN_TYR_URL` is unset, run `/check-titan-tyr-env` first.

## Workflow

### 1. Establish what's changing

Ask the user:

- **`--project <slug>`** — set every touched row's project tag to this
  slug. `__none__` clears the tag. Omit if the sweep is actor-only.
- **`--actor <identity>`** — sent as `X-Actor` on every PUT. Only
  affects rows where `created_by_actor` IS NULL (first-write-wins,
  #54). Omit if the sweep is project-only.

At least one of these must be set or the script refuses.

### 2. Establish what to skip

Ask the user whether they want to narrow the scope:

- **`--current-project <slug | __none__>`** — only operate on rows
  currently in this project. `__none__` selects unprojected rows
  (the common backfill case: "tag everything that isn't tagged
  yet"). Cheap; uses the server-side `?project=` filter.
- **`--current-actor <identity | __none__>`** — only operate on rows
  whose current `created_by_actor` matches. `__none__` selects
  unattributed rows. Filtered client-side after pagination.
- **`--kind parts|contracts|both`** — default `both`. Narrow if the
  user only cares about one side of the graph.

The most common combinations:

| Goal                                                | Flags                                                                |
| --------------------------------------------------- | -------------------------------------------------------------------- |
| Tag every untagged row to a new project             | `--project <slug> --current-project __none__`                        |
| Claim every unattributed row under one actor        | `--actor <identity> --current-actor __none__`                        |
| Move one project's rows wholesale to another        | `--project <new> --current-project <old>`                            |
| Rename actor on every row a person owns (won't work) | not supported — first-write-wins protects already-attributed rows.   |

The last row is a real gotcha: once `created_by_actor` is set on a
row, no PUT can change it. To re-attribute an already-claimed row
you'd need a content-proposal flow, not this sweep.

### 3. Run the dry-run

Hand it to the user before approving:

```sh
.claude/skills/bulk-claim-rows/scripts/bulk-claim-rows.sh \
  [--project <slug>] \
  [--actor <identity>] \
  [--current-project <slug | __none__>] \
  [--current-actor <identity | __none__>] \
  [--kind parts|contracts|both]
```

The script lists every row that *would* change, with current → new
values for project and actor. Rows that would be no-ops (tag already
matches; actor already set; filter excludes) are summarised by count
only.

Read the table with the user. Watch for:

- **Larger row count than expected.** A wrong filter ("`__none__`"
  vs a real slug) is the usual cause.
- **A row already attributed to the wrong identity.** First-write-wins
  means the script *won't* fix that — call it out as a known
  limitation, not a script bug.
- **Parts will bump patch versions.** `PUT /parts/{name}` requires
  `version` + `markdown`, so the script GETs each part, replays its
  current markdown, and bumps PATCH. That's a real version row in
  history. Confirm the user is OK with N patch bumps appearing in
  every part's history.

### 4. Approve

The script prompts `apply N change(s)? [y/N]` after the dry-run. Type
`y` only if the table looks right. Pass `--yes` to skip the prompt
only when running non-interactively.

### 5. Read the summary

The script prints `summary: changed M, skipped N, failed F`. If
`failed > 0` the script exits 1 — re-read the failed lines, fix the
underlying cause (usually `422` on an unknown project slug or `409`
on a part whose patch version was somehow already taken), and re-run.
The sweep is idempotent: rows already at the target state become
no-ops on the next pass.

## After the sweep

- Verify with `GET /projects/{slug}` (or `/list-projects`) that
  `part_count` and `contract_count` match expectations.
- Spot-check one row with `/find-part` or `scripts/list-part-contracts.sh`
  to confirm the project tag and actor stuck (`scripts/` here is the
  repo's top-level dev-tools dir; downstream consumers won't have it
  unless they pulled that script in separately).

## Notes

- The script never deletes rows or content. Worst case it bumps a
  part's patch version with the same body — recoverable, just noisy
  in history.
- The X-Actor header is *only* sent on rows the script intends to
  claim (currently null). It is omitted on rows that are already
  attributed, so the dry-run actor column is honest about what will
  actually take effect.
- The script reads pages of 100 from `/parts` and `/contracts`. On
  very large catalogs (thousands of rows) the dry-run can take a few
  seconds; that's expected.
