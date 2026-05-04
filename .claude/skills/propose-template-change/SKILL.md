---
name: propose-template-change
description: Propose a change to one of titan-tyr's templates (`software`, `container`, `image`, `pod`, `compose`, `interaction`, `binding`, `connection`). Use when the user wants to update the canonical template content served by /templates/{kind} — e.g. "propose changing the interaction template", "draft a template change", "I want to update the software template", "tweak the binding template", "update the connection template", "update the image template", "update the pod template", "update the compose template". Fetches current state, applies the user's edit, picks a version, and POSTs to /templates/{kind}/proposals. Does NOT accept the proposal — acceptance is a deliberate separate step.
---

# propose-template-change

You are drafting a proposed change to one of titan-tyr's templates.
The current set is `software`, `container`, `image`, `pod`,
`compose`, `interaction`, `binding`, `connection` — one per part
subtype (parts: software/container/image/pod/compose) and one per
contract subtype (contracts: interaction/binding/connection).
Templates live in Postgres and evolve through a
propose / accept / RC flow — same machinery as contracts. This skill
**creates the proposal**; it never accepts. Acceptance is the user's
explicit next step (`POST /templates/{kind}/proposals/{version}/accept`).

## Server location

Same env vars as `register-part`:

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |
| `TITAN_TYR_ACTOR` | no       | Identity for the X-Actor header (provider v0.16.0+, #38). The provider records the proposer on the version row; the accept side enforces proposer-doesn't-accept. If unset, the proposal records `null` and any acceptor is allowed — warn the user. |

If `TITAN_TYR_URL` is unset, **stop and tell the user**:

> `TITAN_TYR_URL` is not set. Set it to the titan-tyr base URL before running this skill, e.g.
> `export TITAN_TYR_URL=http://localhost:8000`.

Don't guess. Don't default to localhost silently.

## Workflow

### 1. Confirm reachability and target template

Cheap probe:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → wrong token. Stop.
- Connection refused → wrong URL or server down. Stop.

Ask which template the user wants to change: one of **`software`**,
**`container`**, **`image`**, **`pod`**, **`compose`**,
**`interaction`**, **`binding`**, **`connection`**. Those are the
only valid `kind` values.

### 2. Fetch the current active template

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/{kind}"
```

Show it to the user (or summarise structure if it's long). They need to
see what they're changing **from**.

### 3. Check for existing proposals

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/{kind}/proposals"
```

Note `active_version` and any open `proposals` in the response. Surface
this to the user — they should know if they're competing with an
in-flight draft from someone else, and the version of the latest
proposal sets the floor for the version *they* will need to pick
(see step 5).

### 4. Apply the change

Ask the user how they want to change the template. Three common shapes:

- **Natural-language edit** — "remove the Counterparty column from the
  Ports table." Apply the edit and produce the **complete new body**.
- **Full new body** — user pastes or hands you the entire markdown.
  Use it as-is (modulo a sanity check).
- **Diff or partial fragment** — apply against the current active body
  to produce the complete new body.

titan-tyr stores **full markdown bodies**, not diffs. Whatever shape
the user gave you, the artifact you POST is the entire new body.

### 5. Choose a version

The new version must be **strictly greater than every existing version
on this template** (active *plus* any open proposals — the
strictly-greater check on the server uses the max across both). Pick a
bump that matches the user's intent:

| Change shape                                                | Bump                                                     |
| ----------------------------------------------------------- | -------------------------------------------------------- |
| Breaking (removes a column, renames a section, restructures) | MAJOR (e.g. `1.2.3` → `2.0.0`)                          |
| Additive (new section, new optional field)                  | MINOR (e.g. `1.2.3` → `1.3.0`)                          |
| Clarification (typos, wording, examples)                    | PATCH (e.g. `1.2.3` → `1.2.4`)                          |
| Iterating with reviewers before locking in                  | append `-rcN` to the target (`1.3.0-rc1`, `1.3.0-rc2`)  |

If the user expects review rounds before the change goes live,
**recommend RC iterations** — start with `<target>-rc1`, then bump the
RC number on each revision, then propose the bare `<target>` once
everyone agrees. Acceptance of the bare `<target>` will create the
new active version; the RCs stay in the database for posterity.

If you can compute "the next sensible version" given the user's intent
(e.g. they said "this is breaking" and active is `1.2.0`), suggest it
and let the user override.

### 6. Preview before submitting

Show the user **the full new body** plus the version you intend to
submit. Ask "ready to propose?" Do not POST until the user confirms.
If they want changes, iterate — re-show after each edit.

### 7. Submit

Build the JSON via a tool, not shell heredocs or `-d "..."`. Template
bodies will contain backticks, pipes, asterisks, double quotes, and
unicode — `--data @file.json` written by Python sidesteps every
shell-escaping landmine.

**Scratch files must live inside the project.** Do not write to `/tmp`,
`$HOME`, or any path outside the working directory. Use `.scratch/` at
the repo root (gitignored — create it if it doesn't exist) and clean up
after.

```sh
mkdir -p .scratch
python3 -c "
import json, pathlib
print(json.dumps({
    'version': 'X.Y.Z',  # or 'X.Y.Z-rcN'
    'markdown': pathlib.Path('.scratch/template-proposal.md').read_text(),
}))
" > .scratch/template-proposal.json

curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "Content-Type: application/json" \
     -H "X-Actor: $TITAN_TYR_ACTOR" \
     --data @.scratch/template-proposal.json \
     "$TITAN_TYR_URL/templates/{kind}/proposals"
```

The `X-Actor` header records the proposer for the two-party rule
enforced on accept (provider v0.16.0+, #38). If unset, the
proposal records `proposer_actor: null` and the rule cannot be
enforced — warn the user. Templates affect every consumer; the
two-party gate matters more here than for any single contract.

### 8. Report — and explain accept, but do NOT accept

On `201`, summarise:

> Proposed `<version>` for the `<kind>` template. Status: `proposal`.
>
> List open proposals:
>   `curl -H 'Authorization: Bearer sysmlv2' $TITAN_TYR_URL/templates/<kind>/proposals`
>
> Accept (when ready):
>   `curl -X POST -H 'Authorization: Bearer sysmlv2' \`
>     `$TITAN_TYR_URL/templates/<kind>/proposals/<version>/accept`

**Do not auto-accept.** Even if the user appears to want it landed
immediately, do the propose and the accept as two visible steps so the
review boundary stays explicit. (If the user explicitly says "and
accept it," then run the accept curl after the propose, but call it
out clearly in your reply: "Proposed and accepted in one go because
you asked for that.")

## Error handling

| Status | Meaning                                            | What to do                                                                  |
| ------ | -------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                   | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `404`  | Unknown `kind` (not one of `software`, `container`, `image`, `pod`, `compose`, `interaction`, `binding`, `connection`) | Stop. Re-check the kind value.                            |
| `409`  | `version` not strictly greater than latest         | Bump beyond the current max (active + any open proposals). Suggest a value. |
| `422`  | Malformed `version`                                | Format is `^\d+\.\d+\.\d+(-rc\d+)?$`. No `alpha`/`beta` suffixes.           |
| `5xx`  | Server problem                                     | Print response body verbatim. Do not retry.                                 |

## Notes

- A common pattern: open with `<target>-rc1`, gather review feedback,
  iterate (`<target>-rc2`, `<target>-rc3`), then propose the bare
  `<target>` and accept. All RCs are preserved in the database for
  history; only the final stable becomes active.
- If you're proposing a change that itself updates the **fill rules**
  documented in the `register-part` skill, mention it in the
  proposal body so reviewers know to update the skill in lockstep.
- This skill is for **template content**, not for the API's behavior.
  Endpoint changes go through the regular PR / DESIGN.md flow, not
  through `POST /templates/...`.
- **There is no withdraw or reject.** Once a proposal is POSTed it
  stays in the database. If you decide the proposal is wrong before
  it's accepted, propose a higher version that reflects what you
  actually want and accept that. The dangling earlier proposal is
  preserved for history and drops out of `GET .../proposals` once the
  active version moves past it. Same on the receiver side
  (`/accept-template-proposal`) — the response to a proposal you don't
  like is a counter-proposal, not a rejection.
