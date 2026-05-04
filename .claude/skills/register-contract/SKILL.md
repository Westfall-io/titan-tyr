---
name: register-contract
description: Register a new contract between two parts already in titan-tyr. Branches on subtype — `interaction` (protocol/schema agreement, e.g. "Software A calls Software B over HTTP"), `binding` (environment-specific deployment binding, e.g. "Container payments-prod is reachable at host=payments-prod, port=8080 by software payments-service"), or `connection` (structural binding declared in build/config/deploy artifacts with no runtime data flow, e.g. "this image is built from this repo", "this container depends on that container at startup"). Use when the user wants to create a new contract — e.g. "register a contract from X to Y", "create the binding for payments-prod", "we need an interaction contract between the API and the UI", "record the depends-on between containers". Picks the two part endpoints (with ?match= autocomplete), fetches the matching template, fills it, and POSTs to `/contracts`. Initial creation is `active` immediately — no propose/accept dance for v1.0.0; that's by design.
---

# register-contract

You are helping the user register a new contract — a directed edge
between two parts in titan-tyr's graph. Contracts come in three
subtypes: `interaction` (#24), `binding` (#24), and `connection`
(#32). The skill walks through `POST /contracts`.

Both part endpoints must already exist as registered nodes — if
either is missing, hand off to `/register-part` first. Only one
contract can exist per directed pair (`A → B`) regardless of subtype;
subsequent changes go through `/propose-contract-change` and
`/accept-contract-proposal`.

## Server location

Read these from the environment:

| Variable          | Required | Purpose                                                                                |
| ----------------- | -------- | -------------------------------------------------------------------------------------- |
| `TITAN_TYR_URL`   | yes      | Base URL of the API, e.g. `http://localhost:8000`. No trailing slash.                  |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2` (the placeholder password — see titan-tyr DESIGN.md). |
| `TITAN_TYR_ACTOR` | no       | Identity for the X-Actor header (provider v0.16.0+, #39). Stored as `created_by_actor` on the new contract row — the row's *creator* attribution. If unset, the contract records `null` for the creator and the paper trail starts blank — warn the user. The original creator may claim a `null`-attributed row later via `/update-contract` (first-write-wins backfill, provider v0.21.0+, #54); per-version proposer/acceptor attribution lives on the proposal/accept rows of `/contracts/{id}/proposals` and surfaces in `/contracts/{id}/history` (per-version actor on history landed in v0.21.0+, #54). |

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
  "$TITAN_TYR_URL/templates/interaction" -o /dev/null
```

- `200` → continue.
- `401` → wrong token. Stop.
- Connection refused / DNS failure → wrong URL or server down. Stop.

### 2. Pick the subtype

Ask the user which kind of contract they want, or infer from context.
The three subtypes encode different agreements with different
validation rules:

| Subtype       | What it describes                                                                                    | Source (owner_part)            | Target (counterparty_part)            |
| ------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------ | ------------------------------------- |
| `interaction` | Protocol/schema-level agreement (HTTP API, queue topic, RPC). Env-agnostic. Runtime data flows.      | any                            | any                                   |
| `binding`     | Deployment address binding (host/port/protocol from container or pod to software). Env-specific. Runtime.   | `container` or `pod`           | `software`                            |
| `connection`  | Structural binding declared in build/config/deploy artifacts. **No runtime data flow.**              | depends on `connection_type`   | depends on `connection_type`          |

Quick rule of thumb:

- "How does A talk to B?" / "What's the schema?" → **interaction**
- "Where does the running container expose itself?" / "How does the software find its address?" → **binding**
- "What does X build from / instantiate / depend on at startup / include as a submodule?" → **connection**
- Test for connection vs interaction/binding: if the relationship is declared in a Dockerfile, compose file, k8s manifest, or `.gitmodules` and **no data flows at runtime**, it's a `connection`. If it's expressed in running application code or carries a runtime address, it's `interaction` or `binding`.

If the user says "contract" without qualifying, default to `interaction`
(today's existing behaviour) and confirm.

If the user picked `connection`, also pick the **connection_type** —
one of six labels:

| `connection_type` | Owner part subtype  | Counterparty part subtype | What it records                                     |
| ----------------- | ------------------- | ------------------------- | --------------------------------------------------- |
| `builds-from`     | `software`          | `image`                   | Repository builds into image (Dockerfile + CI)      |
| `instantiates`    | `image`             | `container` or `pod`      | Image is run as a container or pod                  |
| `runs`            | `container` or `pod`| `software`                | Runtime hosts a specific software process            |
| `member-of`       | `container`         | `compose`                 | Container is a service entry in a compose stack     |
| `depends-on`      | `container`         | `container`               | Startup ordering within a compose stack              |
| `submodule`       | `software`          | `software`                | One repository includes another via `.gitmodules`   |

All six labels work end-to-end after #37. The router still has a
deferred-subtype guard for any future rule that references a
not-yet-implemented Part subtype, but no current rule trips it.

The subtype determines which template you fetch in step 7 and shapes
the validation in step 4.

### 3. Resolve the two part endpoints

`POST /contracts` requires `owner_part` and `counterparty_part` —
both as canonical slugs of registered parts. Validate each against the
live catalog using `?match=` so typos and colloquial labels get caught
at this step, not later as a `404`.

For each side (owner, then counterparty):

- If the user gave a canonical slug, `GET /parts/{name}` to confirm
  it exists. Note the `subtype` field — you'll need it for step 4
  validation. `404` → branch to "not registered" handling below.
- If the user gave a colloquial label (`front end`, `payments`,
  `mimiron`), use `GET /parts?match=<label>`. Render hits as
  `<name> v<version> subtype=<software|container> aliases=[...]` and
  ask which one. If exactly one hit, suggest it as the default.
- For `binding` specifically, the source side is a runtime — either
  a container or a pod. Narrow the search with
  `GET /parts?match=<label>&subtype=container` (or `&subtype=pod` for
  K8s topologies) to avoid surfacing unrelated software parts.

**"Not registered" handling.** If either side doesn't exist as a
part, **stop**: the API will `404` and you can't proceed.
Point the user at `/register-part` to create the missing node
first, then come back.

### 4. Subtype-specific validation

Pre-flight the per-subtype rules so the user gets a clear message
before the POST instead of a 422 after.

**`interaction`** — no source/target constraints. Any (part, part)
pair is valid.

**`binding`** — the API enforces:

- `owner_part.subtype IN ("container", "pod")` (the source must be a runtime — either a container or a K8s pod)
- `counterparty_part.subtype == "software"` (the target must be a software part)

Examples to catch:

- User gave two software parts → "binding from software → software
  doesn't make sense; you probably want subtype `interaction`"
- User flipped the direction (software → container/pod) → "binding
  flows outward from the runtime; want me to flip the direction?"
- Source is a container or pod but target is also a runtime → tell
  them and ask what they meant.

**`connection`** — the per-label table from step 2 is the source of
truth. For each `connection_type`, owner and counterparty must each
match the rule's allow-set. Two failure modes worth distinguishing:

1. **Wrong subtype for an implemented label.** E.g. `depends-on` with
   `owner.subtype == "software"`. Tell the user the rule, suggest the
   correct subtype (or a different label that fits what they have).
2. **Label requires an un-implemented Part subtype.** No current
   label is affected after #37 — every arm has both Part subtypes
   shipped. The router still surfaces a clear "not yet implemented"
   error if a future rule references a missing subtype; if the user
   sees that error today, treat it as a regression and stop.

If either check fails, **stop early** — don't POST.

### 5. Confirm direction

Direction is meaningful: contracts are stored as a **directed** edge
from `owner_part` to `counterparty_part`. The convention varies by
subtype:

- **Interaction.** Owner is typically the side that defines / publishes
  the interface — for an HTTP API, that's the server; the consumer is
  the counterparty. For a queue or event topic, owner is the publisher
  schema; the consumer subscribes.
- **Binding.** Owner is the runtime — container or pod — (the side
  that *exposes* the address); counterparty is the software (the side
  that *reads* the address from env vars and constructs its callable
  URL). This follows the direction of the address information, which
  mirrors the direction of inbound traffic.

The schema enforces only that owner ≠ counterparty and that no
contract already exists in that direction (regardless of subtype).
State the intended direction explicitly to the user
("`payments-prod` (owner, container) → `payments-service` (counterparty,
software) — binding") and confirm before proceeding.

Direction also sets the future review handshake — proposals from
either side go through `/propose-contract-change`, but **the proposer
does not accept their own proposal**. The counterparty side accepts
(or counter-proposes a higher RC). See `/accept-contract-proposal` for
the full protocol.

### 6. Refuse gracefully if a contract already exists

Before fetching the template, check:

```sh
curl -fsS -G \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     --data-urlencode "owner=$owner" \
     --data-urlencode "counterparty=$counterparty" \
     "$TITAN_TYR_URL/contracts"
```

If `results` is non-empty for the chosen direction, **stop**: a
contract already exists between this pair. Don't try to register again
— the API will `409`. The right next step is `/propose-contract-change`
to amend the existing one. Surface the existing `contract_id`,
`subtype`, and active `version` so the user has the identifier they
need.

> **Note:** there's only one contract per directed pair regardless of
> subtype. If the existing contract is the wrong subtype for what you
> wanted (e.g. it's `interaction` and you wanted `binding`, or it's a
> `connection` with the wrong `connection_type` label), the resolution
> is *not* to register a second one — file an in-place correction via
> `/propose-contract-subtype-shift` (provider v0.15.0+, titan-tyr#33).
> The shift flow flips the subtype (and, for connection contracts, the
> `connection_type` label) without bumping the version or mutating the
> body, and runs through a separate two-party propose/accept handshake
> via `/accept-contract-proposal`. Surface this as the path forward
> rather than asking the user to tear the contract down out-of-band.

If `results` is empty, continue.

### 7. Fetch the matching template

The template path depends on the subtype you picked in step 2:

| Subtype       | Template URL                              |
| ------------- | ----------------------------------------- |
| `interaction` | `$TITAN_TYR_URL/templates/interaction`    |
| `binding`     | `$TITAN_TYR_URL/templates/binding`        |
| `connection`  | `$TITAN_TYR_URL/templates/connection`     |

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/<subtype>"
```

The body is the scaffold the user fills in. To get the active template
**version** (needed for the stamp substitution in step 8), call:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/<subtype>/proposals" \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['active_version'])"
```

(The body endpoint returns markdown only; the proposals endpoint is
the canonical place to read template metadata.)

### 8. Fill the template

The template is **self-describing** — its instructional blockquotes
(`>` blocks) and any `### …` reference subsections are guidance for
the human / agent doing the fill, not content to save. Read them,
follow them, then strip them from the body you POST.

Generic fill rules — these apply regardless of which template you
fetched (identical to `/register-part`):

1. **`<...>` placeholders are content slots.** Replace each with real
   content and drop the angle brackets.

2. **Reserved meta-placeholders.** Filled by the skill, not the user:
   - `<template-version>` — substitute with the active template version
     you fetched in step 7. The stamp is usually
     `<!-- template: <subtype>@<template-version> -->` at the top of
     the body. Keep the comment line; replace the placeholder.

3. **Instructional blockquotes are filler-only.** Any `>` block whose
   content is guidance to the filler gets stripped. Templates from the
   subtype-aware era onward prefix every such blockquote with
   `**DELETE WHEN FILLING IN.**` to make this unambiguous — when you
   see that marker, drop the whole block.

4. **Pure-reference H3 subsections are filler-only.** If an H3 only
   exists to explain how to fill its parent section, drop it. If it
   invites you to add real content (e.g. errors specific to this
   contract), keep it iff you have real content.

5. **Don't invent structure.** No new H2 sections beyond what the
   template defined. Surplus content goes in the Notes / Feedback
   section the template provides.

The skill stops here on template specifics. What counts as a Provider
Obligation, how to phrase Schema, what protocols accept what fields,
how to populate the binding components table — all of that lives **in
the template body itself**, not in this skill. If you find yourself
wanting to add template-specific guidance here, that's a signal to
`/propose-template-change` instead.

### 9. Preview before submitting

Show the user **the full filled markdown body**, the chosen
`subtype`, the chosen `owner_part` / `counterparty_part` (with
direction restated), and the version you intend to submit (`1.0.0`
unless the user has a reason to start higher). Ask "ready to register?"
Do not POST until the user confirms. If they want changes, iterate —
re-show after each edit.

### 10. Submit

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
payload = {
    'owner_part': 'payments-prod',
    'counterparty_part': 'payments-service',
    'subtype': 'binding',
    'markdown': pathlib.Path('.scratch/contract-body.md').read_text(),
    'version': '1.0.0',
}
# For subtype='connection', also include the connection_type label
# picked in step 2 (e.g. 'depends-on' or 'submodule'):
#   payload['connection_type'] = 'depends-on'
print(json.dumps(payload))
" > .scratch/contract-body.json

curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "Content-Type: application/json" \
     -H "X-Actor: $TITAN_TYR_ACTOR" \
     --data @.scratch/contract-body.json \
     "$TITAN_TYR_URL/contracts"
```

The `X-Actor` header is recorded as `created_by_actor` on the new
contract row (provider v0.16.0+, #39). Initial creation is one-shot
active — no propose/accept dance — so this is the only attribution
the row's existence will ever carry. If `TITAN_TYR_ACTOR` is unset,
the paper trail goes blank — warn the user.

### 11. Report the result

On `201`, summarise:

> Registered `<subtype>` contract `<owner> → <counterparty>` at version
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
needs to drop the dev-server proxy", or "container env var has not
been added yet"), surface them — don't auto-do.

## Error handling

| Status | Meaning                                                                | What to do                                                                  |
| ------ | ---------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                                       | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `404`  | Either `owner_part` or `counterparty_part` is unknown                  | Re-resolve in step 3; route to `/register-part` if truly missing.       |
| `409`  | A contract with the same `(owner, counterparty, subtype, connection_type)` triple already exists | Stop. Show the existing `contract_id` (re-run the search from step 6) and route to `/propose-contract-change`. The widened key (per #42) only conflicts on the full triple — different subtypes (or different `connection_type` values) on the same pair are allowed. |
| `422`  | `owner_part == counterparty_part`, missing/unknown `subtype`, missing or wrong `connection_type` (required iff `subtype=connection`), malformed `version`, slug pattern fail, `binding` source/target subtype mismatch, `connection` source/target subtype mismatch per the per-label rule, `connection_type` whose required Part subtype isn't yet implemented, or unknown `project` slug | Fix and retry. `version` is plain `MAJOR.MINOR.PATCH`. For an unknown `project`, run `/list-projects` or `/register-project`. Re-check the rule table in step 2/4. |
| `500+` | Server problem                                                         | Print response body verbatim. Do not retry.                                 |

## Project tagging (#44)

Contracts can be tagged with an optional `project` slug at registration:

```json
{
  "owner_part": "payments-service",
  "counterparty_part": "orders-service",
  "subtype": "interaction",
  "markdown": "...",
  "project": "watchervault"
}
```

The slug must reference an existing project (422 if not). Importantly,
the contract's `project` is **independent of its endpoints' projects**
— a cross-project contract is allowed and tagged with whichever project
owns the *relationship*, not auto-inherited from the owner. The UI will
show the contract under whichever project it's tagged with.

If the surrounding context makes the project obvious (e.g. both
endpoints are in the same project, or the user just said "we're working
on the watchervault project"), tag the contract proactively. Otherwise
ask, or default to unprojected.

## Notes

- **One row per `(direction, subtype, connection_type)` triple.** The
  schema permits both `A → B` and `B → A` as separate rows. As of #42
  the unique constraint is `(owner_part_id, counterparty_part_id, subtype,
  connection_type) NULLS NOT DISTINCT` — so a single directed pair can
  hold one `interaction`, one `binding`, and one `connection` per
  `connection_type` (six labels, so up to six connection rows + one
  interaction + one binding = eight rows max in one direction). This is
  what enables the multi-row Connections tables in `container@3.0.0`
  and the templates that depend on it. Just because you *can* register
  multiple subtypes on the same pair doesn't mean you *should* — most
  interfaces still need exactly one row in one direction. Pick the
  shape that matches what's actually true: e.g. container `payments-prod`
  → software `payments-service` typically holds both a `connection`/`runs`
  row and a `binding` row (the runs is the structural fact, the binding
  is the address); software `payments-service` → software `orders-service`
  is a single `interaction`.
- **Subtype is structural.** It can't be changed after registration
  (no PUT path mutates it). If you really need a different subtype,
  the contract has to be re-created — out-of-band today.
- **Initial creation is active by design.** This is the only
  contract-mutation endpoint where the result is `active` without an
  acceptance step. The propose/accept flow only exists for subsequent
  versions of an existing contract.
- **No `owner` field beyond `owner_part`.** There is no per-caller
  identity in this API yet (the bearer password is a placeholder; real
  auth is deferred). Put team / individual ownership info in the
  contract markdown body if it matters to humans, not in a JSON field.
- **Don't put a `Version` field inside the markdown body** — the API
  tracks it on the version row separately.
- **All Part subtypes referenced by the connection rule table are
  implemented as of #37.** `image` shipped in #35, `pod` in #36,
  `compose` in #37 — every `connection_type` arm works end-to-end.
  The deferred-subtype check in the router stays in place as a
  guard for any future rule that references a missing subtype.
- **The contract template's fill rules are identical to the part
  template's.** If those rules grow, update both register skills in
  lockstep — same as the propose/accept pair.
