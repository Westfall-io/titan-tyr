---
name: accept-template-proposal
description: Promote an open titan-tyr template proposal (software or contract) to the new active version. Use when the user wants to land a previously-proposed template change — e.g. "accept the template proposal", "promote 2.0.0-rc1 to active", "make this the new template". Lists open proposals, confirms which one to accept, and POSTs to /templates/{kind}/proposals/{version}/accept. Acceptance changes what every caller sees on `GET /templates/{kind}` — confirm before submitting.
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

Ask which template the user wants to accept against: **`software`** or
**`contract`**.

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
  (`POST /contracts/{contract_id}/proposals/{version}/accept`) — out
  of scope for this skill; build a sibling if/when needed.
- **No --data file is needed**, so the JSON-via-file scratch dance the
  other two skills use does not apply here.
- **There is no reject endpoint.** If you don't like a proposal, the
  response is to counter-propose a higher version that reflects what
  you do want, then accept that. Proposals can't be torn down — they
  stay in `*_versions` for history and drop out of
  `GET .../proposals` once the active version moves past them. By
  design; see DESIGN.md → Open Questions §1.
