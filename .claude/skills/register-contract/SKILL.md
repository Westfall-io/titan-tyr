---
name: register-contract
description: Register a new interface contract between two software nodes already in titan-tyr. Use when the user wants to create the binding agreement for how one piece of software talks to another — e.g. "register a contract from X to Y", "we need a contract between the API and the UI", "create the X↔Y interface contract". Picks the two software endpoints (with ?match= autocomplete), fetches the contract template, fills it, and POSTs to /contracts. Initial creation is `active` immediately — no propose/accept dance for v1.0.0; that's by design.
---

# register-contract

You are helping the user register a new interface contract — the
binding agreement between two software nodes describing how one talks
to the other. titan-tyr stores software as nodes and contracts as
directed edges. This skill walks through the **edge creation** path:
`POST /contracts`.

Both software endpoints must already exist as registered nodes — if
either is missing, hand off to `/register-software` first. Only one
contract can exist per directed pair (`A → B`); subsequent changes go
through `/propose-contract-change` and `/accept-contract-proposal`.

## Server location

Read these from the environment:

| Variable          | Required | Purpose                                                                                |
| ----------------- | -------- | -------------------------------------------------------------------------------------- |
| `TITAN_TYR_URL`   | yes      | Base URL of the API, e.g. `http://localhost:8000`. No trailing slash.                  |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2` (the placeholder password — see titan-tyr DESIGN.md). |

If `TITAN_TYR_URL` is unset, **stop and tell the user**:

> `TITAN_TYR_URL` is not set. Set it to the titan-tyr base URL before running this skill, e.g.
> `export TITAN_TYR_URL=http://localhost:8000`.

Don't guess. Don't default to localhost silently.

If `TITAN_TYR_TOKEN` is unset, use `sysmlv2` and mention you are doing
so once in your reply, so the user can override if they're hitting an
instance with a different placeholder.

## Workflow

### 1. Confirm the API is reachable

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/contract" -o /dev/null
```

- `200` → continue.
- `401` → wrong token. Stop.
- Connection refused / DNS failure → wrong URL or server down. Stop.

### 2. Resolve the two software endpoints

`POST /contracts` requires `owner_software` and `counterparty_software`
— both as canonical slugs of registered software nodes. Validate each
against the live catalog using `?match=` so typos and colloquial labels
get caught at this step, not later as a `404`.

For each side (owner, then counterparty):

- If the user gave a canonical slug, `GET /software/{name}` to confirm
  it exists. `404` → branch to "not registered" handling below.
- If the user gave a colloquial label (`front end`, `payments`,
  `mimiron`), use `GET /software?match=<label>`. Render hits as
  `<name> v<version> aliases=[...]` and ask which one. If exactly one
  hit, suggest it as the default.
- If the user only described one side ("a contract for the UI"), help
  them pick the other interactively.

**"Not registered" handling.** If either side doesn't exist as a
software node, **stop**: the API will `404` and you can't proceed.
Point the user at `/register-software` to create the missing node
first, then come back.

### 3. Confirm direction

Direction is meaningful: contracts are stored as a **directed** edge
from `owner_software` to `counterparty_software`. The convention:

- **Owner** is typically the side that defines / publishes the
  interface — for an HTTP API, that's the server.
- **Counterparty** is typically the consumer — the HTTP client.
- For a queue or event topic, owner is the publisher schema; the
  consumer subscribes.

This is convention, not a hard rule. The schema enforces only that
owner ≠ counterparty and that no contract already exists in that
direction. State the intended direction explicitly to the user
("`titan-tyr` (owner, API server) → `titan-mimiron` (counterparty, UI
client)") and confirm before proceeding.

### 4. Refuse gracefully if a contract already exists

Before fetching the template, check:

```sh
curl -fsS -G \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     --data-urlencode "owner=$owner" \
     --data-urlencode "counterparty=$counterparty" \
     "$TITAN_TYR_URL/contracts"
```

If `results` is non-empty for the chosen direction, **stop**: a
contract already exists between this pair. Don't try to register
again — the API will `409`. The right next step is
`/propose-contract-change` to amend the existing one. Surface the
existing `contract_id` and active `version` so the user has the
identifier they need.

If `results` is empty, continue.

### 5. Fetch the contract template

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/contract"
```

The body is the scaffold the user fills in. To get the active template
**version** (needed for the stamp substitution in step 6), call:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/contract/proposals" \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['active_version'])"
```

(The body endpoint returns markdown only; the proposals endpoint is
the canonical place to read template metadata.)

### 6. Fill the template

The template is **self-describing** — its instructional blockquotes
(`>` blocks) and any `### …` reference subsections are guidance for
the human / agent doing the fill, not content to save. Read them,
follow them, then strip them from the body you POST.

Generic fill rules — these apply regardless of what's in the template
(identical to `/register-software`):

1. **`<...>` placeholders are content slots.** Replace each with real
   content and drop the angle brackets.

2. **Reserved meta-placeholders.** Filled by the skill, not the user:
   - `<template-version>` — substitute with the active contract
     template version you fetched in step 5. The stamp is usually
     `<!-- template: contract@<template-version> -->` at the top of
     the body. Keep the comment line; replace the placeholder.

3. **Instructional blockquotes are filler-only.** Any `>` block whose
   content is guidance to the filler gets stripped. Templates from
   `contract@1.2.0` onward prefix every such blockquote with
   `**DELETE WHEN FILLING IN.**` to make this unambiguous — when you
   see that marker, drop the whole block.

4. **Pure-reference H3 subsections are filler-only.** If an H3 only
   exists to explain how to fill its parent section, drop it. If it
   invites you to add real content (e.g. errors specific to this
   contract), keep it iff you have real content.

5. **Don't invent structure.** No new H2 sections beyond what the
   template defined. Surplus content goes in the Notes section the
   template provides.

The skill stops here on template specifics. What counts as a Provider
Obligation, how to phrase Schema, what protocols accept what fields —
all of that lives **in the template body itself**, not in this skill.
If you find yourself wanting to add template-specific guidance here,
that's a signal to `/propose-template-change` instead.

### 7. Preview before submitting

Show the user **the full filled markdown body**, the chosen
`owner_software` / `counterparty_software` (with direction restated),
and the version you intend to submit (`1.0.0` unless the user has a
reason to start higher). Ask "ready to register?" Do not POST until
the user confirms. If they want changes, iterate — re-show after each
edit.

### 8. Submit

**Scratch files must live inside the project.** Use `.scratch/` at the
repo root (gitignored — create it if it doesn't exist) and clean up
after.

**Build the JSON body via a tool, not via shell heredocs or `-d "..."`.**
Contract markdown will contain backticks, pipes, asterisks, double
quotes, and unicode — `--data @file.json` written by Python sidesteps
every shell-escaping landmine.

```sh
mkdir -p .scratch
python3 -c "
import json, pathlib
print(json.dumps({
    'owner_software': 'titan-tyr',
    'counterparty_software': 'titan-mimiron',
    'markdown': pathlib.Path('.scratch/contract-body.md').read_text(),
    'version': '1.0.0',
}))
" > .scratch/contract-body.json

curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "Content-Type: application/json" \
     --data @.scratch/contract-body.json \
     "$TITAN_TYR_URL/contracts"
```

### 9. Report the result

On `201`, summarise:

> Registered contract `<owner> → <counterparty>` at version
> `<version>`. Contract ID: `<contract_id>`. Status: `active`.
>
> Read it back:
>   `curl -H 'Authorization: Bearer sysmlv2' $TITAN_TYR_URL/contracts/<contract_id>`
>
> Subsequent changes:
>   - Propose: `/propose-contract-change` (or raw POST /contracts/<contract_id>/proposals)
>   - Accept: `/accept-contract-proposal`

Initial creation is **`active` immediately** — there is no
propose/accept dance for v1.0.0. That's by design (the API has no
"draft contract" state at creation; the propose/accept flow only
applies to subsequent versions). If the user wanted a review gate
before the contract went live, the right pattern is: register at
v1.0.0 (which is essentially a strawman), then immediately propose
v1.1.0-rc1 with the actually-agreed body and iterate from there. Flag
this option when the contract is high-stakes.

If the contract body called out cross-repo follow-ups (e.g. "consumer
needs to drop the dev-server proxy"), surface them — don't auto-do.

## Error handling

| Status | Meaning                                                                | What to do                                                                  |
| ------ | ---------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                                       | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `404`  | Either `owner_software` or `counterparty_software` is unknown          | Re-resolve in step 2; route to `/register-software` if truly missing.       |
| `409`  | A contract already exists in this direction                            | Stop. Show the existing `contract_id` (re-run the search from step 4) and route to `/propose-contract-change`. |
| `422`  | `owner_software == counterparty_software`, malformed `version`, or either software reference fails the slug pattern | Fix and retry. `version` is plain `MAJOR.MINOR.PATCH`. |
| `500+` | Server problem                                                         | Print response body verbatim. Do not retry.                                 |

## Notes

- **One direction, one contract.** The schema permits both
  `A → B` and `B → A` (they're separate rows), but they're often not
  both meaningful. Most interfaces are described from one side; only
  register the reverse direction if there's a genuinely separate
  agreement going the other way.
- **Initial creation is active by design.** This is the only
  contract-mutation endpoint where the result is `active` without an
  acceptance step. The propose/accept flow only exists for subsequent
  versions of an existing contract.
- **No `owner` field beyond `owner_software`.** There is no per-caller
  identity in this API yet (the bearer password is a placeholder; real
  auth is deferred). Put team / individual ownership info in the
  contract markdown body if it matters to humans, not in a JSON field.
- **Don't put a `Version` field inside the markdown body** — the API
  tracks it on the version row separately.
- **The contract template's fill rules are identical to the software
  template's.** If those rules grow, update both register skills in
  lockstep — same as the propose/accept pair.
