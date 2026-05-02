---
name: accept-contract-proposal
description: Promote an open titan-tyr contract proposal to the new active version. Use when the user wants to land a previously-proposed contract change — e.g. "accept the contract proposal", "promote 1.1.0-rc1 to active", "make this the new contract". Helps the user pick the contract (by ID, by software, or from a list), shows a unified diff between active and proposal, and POSTs to /contracts/{contract_id}/proposals/{version}/accept. Acceptance changes what every caller sees on `GET /contracts/{contract_id}` — confirm before submitting.
---

# accept-contract-proposal

You are promoting a previously-drafted contract proposal to the new
**active** version. Acceptance is the deliberate counterpart to the
propose flow: propose drafts and submits, this skill lands.

This skill mutates *what every caller sees* on the next
`GET /contracts/{contract_id}`. Treat the final POST as load-bearing:
do not run it without an explicit user confirmation on the exact
contract + version about to land.

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

### 1. Confirm reachability

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → wrong token. Stop.
- Connection refused → wrong URL or server down. Stop.

### 2. Resolve the contract

Contracts are addressed by `contract_id` (UUID), not by name. **Don't
ask the user to type a UUID from memory.** Branch on what the user
gave you:

- **They gave a `contract_id` (UUID).** Use it directly. Continue to
  step 3.
- **They gave a software name.** List the contracts touching that
  software:

  ```sh
  curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
    "$TITAN_TYR_URL/software/{name}/contracts?limit=100"
  ```

  Each entry has `contract_id`, `owner`, `counterparty`, `version`,
  `updated_at`. Render them as a numbered list (`owner → counterparty
  v<version>`) and ask which one. If there's only one, suggest it as
  the default. `404` → unknown software; stop and offer
  `/find-software`.

- **They gave nothing.** List all contracts (paginated):

  ```sh
  curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
    "$TITAN_TYR_URL/contracts?limit=100"
  ```

  Render `owner → counterparty v<version>` and ask which one. If the
  result set is paginated (`next` is non-null), warn that you've shown
  the first page and offer to drill in by software name instead.

### 3. List open proposals on the chosen contract

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}/proposals"
```

Show `active_version` and the full list of open proposals
(version + created_at). They must see what's available before picking.

If `proposals` is empty, **stop**: there is nothing to accept. Tell
the user — they likely want the propose flow first (currently raw
`POST /contracts/{contract_id}/proposals`; sibling skill is on
the roadmap).

### 4. Confirm the target version

Ask which proposal version to accept. Default sensibly:

- If there's a single bare `MAJOR.MINOR.PATCH` proposal, that's the
  natural promote target — suggest it.
- If only RC versions exist (`X.Y.Z-rcN`), ask which RC to accept and
  warn that the server will create a new stable `X.Y.Z` active row
  from the RC body; the RC row itself stays as `proposal` for posterity.
- If both exist for the same target (`X.Y.Z-rc2`, `X.Y.Z-rc3`,
  `X.Y.Z`), the bare version is almost always the right choice — RC
  rows are review artifacts.

### 5. Show a unified diff vs the active body

The most useful preview is the **diff**, not the full proposal body —
contract proposals often change a single bullet inside a long body.

Fetch the current active body:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}"
```

The proposal body is already in the JSON from step 3 — pull it from
there. Render a unified diff (Python's `difflib.unified_diff` is
fine):

```python
import difflib
diff = difflib.unified_diff(
    active_markdown.splitlines(keepends=True),
    proposal_markdown.splitlines(keepends=True),
    fromfile=f"active {active_version}",
    tofile=f"proposal {proposal_version}",
    n=3,
)
print("".join(diff))
```

If the diff is empty (proposal body identical to active), surface that
loud — accepting will succeed but is a no-op for readers.

### 6. Confirm

Ask explicitly:

> About to accept proposal `<version>` on contract `<owner> →
> <counterparty>` (`<contract_id>`) against `$TITAN_TYR_URL`. After
> this, `GET /contracts/<contract_id>` will return the
> `<resulting-active-version>` body shown above. Proceed?

Wait for an unambiguous yes. "Looks good" is yes; silence is not.

Acceptance is reversible only by proposing yet another version that
restores the prior body — there is no "undo accept" endpoint. So a
clean confirmation step matters more here than on propose.

### 7. Submit

```sh
curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     "$TITAN_TYR_URL/contracts/{contract_id}/proposals/{version}/accept"
```

No request body — the path is the entire input.

### 8. Report

On `200`, summarise the response:

> Accepted. Contract `<owner> → <counterparty>` is now at
> `<active_version>` (promoted from `<promoted_from_version>` at
> `<accepted_at>`).
>
> Verify:
>   `curl -H 'Authorization: Bearer sysmlv2' $TITAN_TYR_URL/contracts/<contract_id>`

Then flag any companion follow-ups the proposal body called out (e.g.
"once accepted, mimiron should drop its CORS proxy" or similar).
Don't auto-do them — surface them and ask.

## Error handling

| Status | Meaning                                                                   | What to do                                                                  |
| ------ | ------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                                          | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `404`  | Unknown contract or proposal version                                      | Re-list proposals; the version may have been a typo, or the contract id is wrong. |
| `409`  | Version not in `proposal` status (already accepted), or RC's stable target already exists | Re-list proposals; the state has moved since you last looked.               |
| `422`  | Malformed version in the path (`^\d+\.\d+\.\d+(-rc\d+)?$`) or contract id not a UUID | Fix the path and retry.                                                     |
| `5xx`  | Server problem                                                            | Print response body verbatim. Do not retry.                                 |

## Notes

- **RC promotion creates a new row.** Accepting `1.3.0-rc2` produces
  active `1.3.0` (suffix stripped, body copied). The `1.3.0-rc2` row
  stays as `proposal` so the review history is preserved. Earlier RCs
  for the same target also remain as `proposal`.
- **Stable promotion is in-place.** Accepting bare `1.3.0` flips the
  same row from `proposal` → `active`. Same body, same `version`,
  just `accepted_at` set and status changed.
- **"Owner accepts" is governance language, not an API gate.** Every
  registered contract carries a "Change protocol" section that says,
  paraphrasing, "the owner software accepts the proposal." That's a
  *role* statement (which party in the agreement holds the decision)
  — not a permissions check on the endpoint. Any caller with a valid
  bearer token can hit `/accept`. In single-operator setups (one
  human owns both sides of the contract, one bearer token everywhere),
  the agent should run `/accept` itself rather than ask another party
  to do it. Defer to the named role only when there are genuinely
  separate teams with conflicting interests, and even then only as a
  process choice, not a technical constraint.
- **Contracts only.** This skill drives
  `POST /contracts/{contract_id}/proposals/{version}/accept`. Template
  proposals have a parallel endpoint
  (`POST /templates/{kind}/proposals/{version}/accept`) — that's
  `/accept-template-proposal`'s job.
- **No propose-contract-change skill yet.** The propose half of the
  contract loop is currently raw
  `POST /contracts/{contract_id}/proposals`. A sibling skill mirroring
  `/propose-template-change` is on the roadmap.
- **No --data file is needed**, so the JSON-via-file scratch dance the
  register/update skills use does not apply here.
- **There is no reject endpoint.** If you don't like a proposal, the
  response is to counter-propose a higher version that reflects what
  you do want, then accept that. Proposals can't be torn down — they
  stay in `*_versions` for history and drop out of
  `GET .../proposals` once the active version moves past them. By
  design; see DESIGN.md → Open Questions §1.
