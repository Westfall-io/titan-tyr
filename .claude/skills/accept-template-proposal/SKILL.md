---
name: accept-template-proposal
description: Promote an open titan-tyr template proposal (software, container, image, pod, compose, interaction, binding, or connection) to the new active version. Use when the user wants to land a previously-proposed template change — e.g. "accept the template proposal", "promote 2.0.0-rc1 to active", "make this the new template". Lists open proposals, confirms which one to accept, and POSTs to /templates/{kind}/proposals/{version}/accept. Acceptance changes what every caller sees on `GET /templates/{kind}` — confirm before submitting.
---

# accept-template-proposal

You are promoting a previously-drafted template proposal to the new
**active** version. Acceptance is the deliberate counterpart to
`/propose-template-change`: the propose skill draft and submits, this
skill lands.

This is the only skill in the trio that mutates *what every caller
sees* on the next `GET /templates/{kind}`. Treat the final POST as
load-bearing: do not run it without an explicit user confirmation on
the exact version about to land.

## Server location

Same env vars as the other titan-tyr skills:

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |

If `TITAN_TYR_URL` is unset, **stop and tell the user**:

> `TITAN_TYR_URL` is not set. Set it to the titan-tyr base URL before running this skill, e.g.
> `export TITAN_TYR_URL=http://localhost:8000`.

Don't guess. Don't default to localhost silently.

## Workflow

### 1. Confirm reachability and target template

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → wrong token. Stop.
- Connection refused → wrong URL or server down. Stop.

Ask which template the user wants to accept against. Eight kinds
today, one per part subtype and one per contract subtype:

- **`software`** — for software parts (codebases / deployables)
- **`container`** — for container parts (Docker / Compose runtimes)
- **`image`** — for image parts (built artifacts between source and runtime)
- **`pod`** — for pod parts (K8s scheduled units of one or more containers)
- **`compose`** — for compose parts (Docker Compose stacks)
- **`interaction`** — for interaction contracts (env-agnostic, any pair, runtime data flows)
- **`binding`** — for binding contracts (container or pod → software, env-specific runtime address)
- **`connection`** — for connection contracts (structural binding, no runtime data flow)

(The legacy `contract` kind was renamed to `interaction` in v0.10.0
and is no longer accepted.)

### 2. List open proposals

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/{kind}/proposals"
```

Show the user `active_version` and the full list of open proposals
(version + created_at). They must see what's available before picking.

If `proposals` is empty, **stop**: there is nothing to accept. Tell
the user — they likely want `/propose-template-change` first.

### 3. Confirm the target version

Ask which proposal version to accept. Default sensibly:

- If there's a single bare `MAJOR.MINOR.PATCH` proposal, that's the
  natural promote target — suggest it.
- If only RC versions exist (`X.Y.Z-rcN`), ask which RC to accept and
  warn that the server will create a new stable `X.Y.Z` active row
  from the RC body; the RC row itself stays as `proposal` for posterity.
- If both exist for the same target (`X.Y.Z-rc2`, `X.Y.Z-rc3`,
  `X.Y.Z`), the bare version is almost always the right choice — RC
  rows are review artifacts.

### 4. Show the body about to become active

Fetch the full markdown of the chosen proposal and show it (or a
clear summary if very long):

```sh
# The list endpoint already returned `markdown` for each proposal —
# pull that field out of the JSON you already have. Don't re-fetch.
```

This is the **last preview** before the change is visible to every
caller. Spelling fixes, leftover scratch text, accidental "TODO"
comments — catch them now.

### 5. Confirm

Ask explicitly:

> About to accept `<kind>` proposal `<version>` against
> `$TITAN_TYR_URL`. After this, `GET /templates/<kind>` will return
> `<resulting-active-version>` body. Proceed?

Wait for an unambiguous yes. "Looks good" is yes; silence is not.

Acceptance is reversible only by proposing yet another version that
restores the prior body — there is no "undo accept" endpoint. So a
clean confirmation step matters more here than on propose.

### 6. Submit

```sh
curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     "$TITAN_TYR_URL/templates/{kind}/proposals/{version}/accept"
```

No request body — the path is the entire input.

### 7. Report

On `200`, summarise the response:

> Accepted. `<kind>` template active version is now `<active_version>`
> (promoted from `<promoted_from_version>` at `<accepted_at>`).
>
> Verify:
>   `curl -H 'Authorization: Bearer sysmlv2' $TITAN_TYR_URL/templates/<kind>`

Then flag any companion follow-ups the proposal body called out (it's
a common pattern for the proposal markdown to note "update skill X" or
similar). Don't auto-do them — surface them and ask.

### 8. Audit downstream resources

Acceptance shifts the template every *new* registration sees, but
existing resources keep the stamp they were registered with. Every
template promotion creates a tail of resources whose stamp now points
at an older version than the one the API hands out. Each one should be
re-stamped (or content-realigned, if the new template restructured a
section).

Pick the audit recipe based on the kind that just landed:

| Accepted kind   | Audit query                                                                                                             | Then for each result                                                                              |
| --------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `software`      | `GET $TITAN_TYR_URL/parts?subtype=software&limit=100`                                                                   | `GET /parts/{name}`, read the stamp on line 1 of `markdown`. If older than active → realign needed. |
| `container`     | `GET $TITAN_TYR_URL/parts?subtype=container&limit=100`                                                                  | Same — `GET /parts/{name}`, check stamp.                                                          |
| `image`         | `GET $TITAN_TYR_URL/parts?subtype=image&limit=100`                                                                      | Same — `GET /parts/{name}`, check stamp.                                                          |
| `pod`           | `GET $TITAN_TYR_URL/parts?subtype=pod&limit=100`                                                                        | Same — `GET /parts/{name}`, check stamp.                                                          |
| `compose`       | `GET $TITAN_TYR_URL/parts?subtype=compose&limit=100`                                                                    | Same — `GET /parts/{name}`, check stamp.                                                          |
| `interaction`   | `GET $TITAN_TYR_URL/contracts?subtype=interaction&limit=100`                                                            | `GET /contracts/{contract_id}`, check stamp on line 1 of `markdown`.                              |
| `binding`       | `GET $TITAN_TYR_URL/contracts?subtype=binding&limit=100`                                                                | `GET /contracts/{contract_id}`, check stamp.                                                      |
| `connection`    | `GET $TITAN_TYR_URL/contracts?subtype=connection&limit=100`                                                             | `GET /contracts/{contract_id}`, check stamp.                                                      |

A compact one-liner:

```sh
# example: software template just landed
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts?subtype=software&limit=100" \
  | python3 -c "
import json, sys, urllib.request, os
listing = json.load(sys.stdin)
for entry in listing['results']:
    req = urllib.request.Request(
        f\"{os.environ['TITAN_TYR_URL']}/parts/{entry['name']}\",
        headers={'Authorization': f\"Bearer {os.environ.get('TITAN_TYR_TOKEN', 'sysmlv2')}\"})
    body = json.load(urllib.request.urlopen(req))
    stamp = body['markdown'].split(chr(10), 1)[0]
    print(f\"{entry['name']:<40} {stamp}\")
"
```

Surface the list to the user with a "needs realign" annotation on
every entry whose stamp version is below the new active. **Don't
auto-file the issues** — surface the list and let the user confirm
scope first. Once confirmed, file one realign issue per resource on
the *owner* side (see realign convention below).

**Realign convention for contract templates** (`interaction` /
`binding` / `connection`): file the realign ticket on the
**counterparty side only**, not on both sides of every contract. The contract owner naturally re-stamps
during their own acceptance flow when they propose the next change;
filing on both sides duplicates work. For part templates
(`software`/`container`), file on the part owner — there's no
counterparty for parts.

### 9. Stamp-only patch-bump recipe

When a contract body is correct in *content* but carries a stale
*stamp* (the template was renamed/bumped after the contract body was
last edited), the right fix is a **patch-bump whose only diff is the
stamp line**. This is the recipe to recommend in step 8 realign
tickets when the contract content needs no other changes.

Mechanics:

- **Owner repo** — propose `<active>.PATCH+1-rc1` against the contract,
  diff = stamp line only, then accept.
- **Counterparty repo** — propose `<active>.PATCH+1-rc1`, diff = stamp
  line only. The owner accepts (per the proposer-doesn't-accept rule).
- **RC, not bare stable.** Even though there's no negotiation,
  proposing as `-rc1` keeps the recipe consistent with the rest of
  the propose/accept flow and avoids confusion if a second clarification
  needs to land before promotion.
- **No changelog entry required**, but a one-liner like
  `**X.Y.Z** — re-stamp body to <kind>@<version> (no behavior change).`
  rounds out the body if you're touching the file anyway.

Why this exists: when a contract proposal lands at the same time as a
template proposal that renames or restructures the kind, an
acceptance-order race can bake a now-invalid stamp into the active
contract body. Once the active version is sealed, you can't supersede
it with another `-rcN` against the same target (409 — the stable
target's RC slot is gone). The patch-bump is the only recourse. See
`/propose-contract-change` step 4b/5 for the pre-flight that prevents
the race in the first place.

## Error handling

| Status | Meaning                                                                   | What to do                                                                  |
| ------ | ------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                                          | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `404`  | Unknown `kind`, contract/template, or proposal version                    | Re-list proposals; the version may have been a typo.                        |
| `409`  | Version not in `proposal` status (already accepted), or RC's stable target already exists | Re-list proposals; the state has moved since you last looked.               |
| `422`  | Malformed version in the path (`^\d+\.\d+\.\d+(-rc\d+)?$`)                | Fix the path and retry.                                                     |
| `5xx`  | Server problem                                                            | Print response body verbatim. Do not retry.                                 |

## Notes

- **RC promotion creates a new row.** Accepting `1.3.0-rc2` produces
  active `1.3.0` (suffix stripped, body copied). The `1.3.0-rc2` row
  stays as `proposal` so the review history is preserved. Earlier RCs
  for the same target also remain as `proposal`.
- **Stable promotion is in-place.** Accepting bare `1.3.0` flips the
  same row from `proposal` → `active`. Same body, same `version`,
  just `accepted_at` set and status changed.
- **Templates only.** This skill drives `POST /templates/{kind}/proposals/{version}/accept`.
  Contract proposals have a parallel endpoint
  (`POST /contracts/{contract_id}/proposals/{version}/accept`) —
  that's `/accept-contract-proposal`'s job.
- **"Owner accepts" is governance language, not an API gate.**
  Templates don't have an owner field, but the same caveat that
  applies to contract proposals applies here: any caller with a valid
  bearer token can hit `/accept`. In single-operator setups, the
  agent should run `/accept` itself rather than defer to another
  party. Only defer when there are genuinely separate teams with
  conflicting interests, and then only as a process choice, not a
  technical constraint.
- **No --data file is needed**, so the JSON-via-file scratch dance the
  other two skills use does not apply here.
- **Don't accept stable before downstream is ready.** Templates are
  filled at registration time and the stamp is preserved per-resource,
  so accepting a stable template change while no part/contract has
  migrated isn't catastrophic — but it does immediately become the
  template every new registration sees. If the new template adds
  required sections or restructures a fill rule, leave it on `-rcN`
  until the register/update skills have been updated to match (or at
  minimum until you've documented the migration plan in the proposal
  body). The lower-stakes analogue of the contract version of this
  rule.
- **There is no reject endpoint.** If you don't like a proposal, the
  response is to counter-propose a higher version that reflects what
  you do want, then accept that. Proposals can't be torn down — they
  stay in `*_versions` for history and drop out of
  `GET .../proposals` once the active version moves past them. By
  design; see DESIGN.md → Open Questions §1.
