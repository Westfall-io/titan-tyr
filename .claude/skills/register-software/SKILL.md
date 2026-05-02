---
name: register-software
description: Register a piece of software with the titan-tyr API. Use when the user wants to add a new software node to WatcherVault's graph — e.g. "register this repo with titan-tyr", "add my service to the WatcherVault catalog", "create a software node for X". Fetches the current `software` template, helps the user fill it in, then POSTs to /software.
---

# register-software

You are helping the user register a piece of software with titan-tyr — the
WatcherVault REST API. titan-tyr stores software as nodes in a graph and
contracts as edges. This skill walks through the **node creation** path:
`POST /software`.

## Server location

Read these from the environment:

| Variable          | Required | Purpose                                                                                |
| ----------------- | -------- | -------------------------------------------------------------------------------------- |
| `TITAN_TYR_URL`   | yes      | Base URL of the API, e.g. `http://localhost:8000`. No trailing slash.                  |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2` (the placeholder password — see titan-tyr DESIGN.md). |

If `TITAN_TYR_URL` is unset, **stop and tell the user**:

> `TITAN_TYR_URL` is not set. Set it to the titan-tyr base URL before running this skill, e.g.
> `export TITAN_TYR_URL=http://localhost:8000`.

Do not try to guess the URL. Do not default to localhost silently.

If `TITAN_TYR_TOKEN` is unset, use `sysmlv2` and mention you are doing so once
in your reply, so the user can override if they're hitting an instance with a
different placeholder.

## Workflow

### 1. Confirm the API is reachable

Before doing anything else, hit a cheap endpoint to fail fast on bad config:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → bearer token is wrong. Tell the user; do not proceed.
- Connection refused / DNS failure → the URL is wrong or the server isn't running. Tell the user.

### 2. Gather the inputs

The `POST /software` body has these fields. Confirm each with the user
before the request — don't invent values:

| Field               | Source                                                                                     |
| ------------------- | ------------------------------------------------------------------------------------------ |
| `name`              | Unique identifier for this software in titan-tyr. Ask the user; suggest the repo name.     |
| `repo_uri`          | Git URL. Read from `git config --get remote.origin.url` if available; confirm with user.   |
| `issue_tracker_uri` | Optional. Where to file tickets if not the repo's default Issues tracker. Ask only if the user uses Jira/Linear/etc.; otherwise omit and consumers fall back to `<repo_uri>/issues`. Must be a valid `https://` URL — the API rejects `http://` and malformed values with 422. |
| `aliases`           | Optional list of colloquial labels other agents may use to refer to this software (`payments`, `billing`, `front end`, `前端`). Used by `GET /software?match=<query>` for fuzzy lookup. Ask the user if there are common nicknames the canonical slug would miss; otherwise omit (defaults to `[]`). Per-entry rules: 1–128 chars, no control chars or newlines, Unicode allowed; case is preserved on storage; case-insensitive dedupe within a single payload. Cross-software collisions are allowed by design. |
| `markdown`          | The filled-in software template body (see step 3).                                         |
| `version`           | Optional; defaults to `"1.0.0"`. Ask only if the user has a reason to start at something else. |

### 3. Fetch the template

Pull the current software template from the API:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" "$TITAN_TYR_URL/templates/software"
```

### 4. Fill the template

The template is **self-describing** — its instructional blockquotes
(`>` blocks) and any `### …` reference subsections are guidance for
the human / agent doing the fill, not content to save. Read them,
follow them, then strip them from the body you POST.

Generic fill rules — these apply regardless of what's in the template:

1. **`<...>` placeholders are content slots.** Replace each with real
   content and drop the angle brackets. `<software-name>` →
   `payments-service`.

2. **Reserved meta-placeholders.** A small fixed set of `<...>` slots
   are filled by the skill, not the user. The only one today:
   - `<template-version>` — substitute with the active template
     version you fetched from `GET /templates/<kind>` (currently
     `2.1.0` for `software`). The stamp is usually
     `<!-- template: software@<template-version> -->` at the top of
     the body. Keep the comment line; replace the placeholder.

3. **Instructional blockquotes are filler-only.** Any `>` block whose
   content is guidance to the filler (rather than something the
   software actually wants to record) gets stripped. Templates from
   `software@2.4.0` / `contract@1.2.0` onward prefix every such
   blockquote with `**DELETE WHEN FILLING IN.**` to make this
   unambiguous — when you see that marker, drop the whole block.

4. **Pure-reference H3 subsections are filler-only.** If an H3 only
   exists to explain how to fill its parent section, drop it. If it
   invites you to add real content (e.g. exclusions, exceptions
   specific to this software), keep it iff you have real content.

5. **Don't invent structure.** No new H2 sections beyond what the
   template defined. Surplus content that doesn't fit goes in the
   Notes section the template provides.

The skill stops here on template specifics. Anything beyond these
generic rules — what counts as a Port, how to phrase Purpose, etc. —
belongs **in the template body itself**, not in this skill. If you
find yourself wanting to add template-specific guidance here, that's
a signal to `/propose-template-change` instead.

### 5. Preview before submitting

Show the user the **full filled markdown body** you intend to POST.
Ask "ready to register?" Do not POST until the user confirms. If they
want changes, iterate — re-show after each edit.

### 6. Submit

**Scratch files must live inside the project.** Do not write to `/tmp`,
`$HOME`, or any path outside the working directory. Use `.scratch/` at
the repo root (gitignored — create it if it doesn't exist) and clean up
after.

**Build the JSON body via a tool, not via shell heredocs or `-d "..."`.**
The markdown will contain backticks, pipes, asterisks, double quotes,
and unicode characters; `--data @file.json` written by Python or `jq`
sidesteps every shell-escaping landmine.

```sh
mkdir -p .scratch
python3 -c "
import json, pathlib
print(json.dumps({
    'name': 'payments-service',
    'repo_uri': 'https://github.com/example/payments-service',
    # 'aliases': ['payments', 'billing'],   # uncomment if the user gave any
    'markdown': pathlib.Path('.scratch/body.md').read_text(),
    'version': '1.0.0',
}))
" > .scratch/body.json

curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "Content-Type: application/json" \
     --data @.scratch/body.json \
     "$TITAN_TYR_URL/software"
```

### 7. Report the result

On `201`, summarise:

> Registered `<name>` at version `1.0.0`. Software ID: `<uuid>`.
> Read it back with: `curl -H 'Authorization: Bearer $TITAN_TYR_TOKEN' $TITAN_TYR_URL/software/<name>`

Ask whether the user wants to also register interface contracts for
this software (one `POST /contracts` per directed edge between this
software and another registered software). Do NOT do that
automatically — both endpoints of the edge must already exist as
software nodes.

## Error handling

| Status | Meaning                                            | What to do                                                                  |
| ------ | -------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                   | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `409`  | A software with that `name` already exists         | Show what's there (`GET /software/{name}`); ask whether to update via `PUT`. |
| `422`  | Malformed `version` (e.g. RC suffix or `1.0`)      | Software versions are plain `MAJOR.MINOR.PATCH`. Suggest a fix.             |
| `500+` | Server problem                                     | Print the response body verbatim. Do not retry.                             |

## Notes

- **Do not** put a `Version` field inside the markdown body — the API tracks
  it on the version row separately. The template's header note explains why.
- **Do not** invent an `owner` field in the JSON body. There is no per-caller
  identity in this API yet (the bearer password is a placeholder; real auth
  is deferred). Put owner info in the markdown body if it matters to humans.
- The very first version of a piece of software is created atomically with
  the software node; you can't register a software without an initial
  markdown body.
