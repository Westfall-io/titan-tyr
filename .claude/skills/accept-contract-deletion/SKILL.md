---
name: accept-contract-deletion
description: Accept an open contract deletion proposal — soft-delete the contract row by stamping `deleted_at` plus the proposer / acceptor / rationale columns. Use when the user wants to land a previously-proposed deletion — e.g. "accept the deletion on contract abc123", "retire that contract now". Lists open deletion proposals on the contract, re-shows the impact block one more time before the irreversible step, and POSTs to /contracts/{contract_id}/deletion-proposals/{proposal_id}/accept. Enforces the proposer-doesn't-accept rule via the X-Actor header (with `?single_operator=true` as the documented override). After acceptance the contract is hidden from default reads and all write endpoints 404; only `?include_deleted=true` reads can see it.
---

# accept-contract-deletion

You are promoting a previously-drafted contract deletion proposal
to `accepted`. Acceptance soft-deletes the contract row: it sets
`deleted_at`, copies the proposer / acceptor / rationale onto the
row, and hides the contract from default reads. The proposal row
itself stays around so the audit trail is complete.

This is the **only mutating step** in the contract deletion flow.
Treat the final POST as load-bearing: do not run it without an
explicit user confirmation on the exact proposal about to land,
and **do not run it under the same `X-Actor` as the proposer**
(proposer-doesn't-accept rule, with `?single_operator=true` as the
documented override).

There is no automatic restoration. After accept the only path to
re-establish the same `(owner, counterparty, subtype,
connection_type)` is to register a fresh contract — which is
allowed because the uniqueness key is partial-on-live.

## Server location

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |
| `TITAN_TYR_ACTOR` | no       | Identity for the X-Actor header. **Strongly recommended** here — without it the two-party rule cannot be enforced and the API allows anyone to accept. |

If `TITAN_TYR_URL` is unset, **stop and tell the user**.

## Workflow

### 1. Confirm reachability and target contract

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET /templates/software \
  -o /dev/null
```

Then verify the contract is still live:

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET /contracts/{contract_id}
```

`404` → the contract is gone. Either the id is wrong or someone
else accepted a deletion in the meantime. Try
`?include_deleted=true`; if it shows up, the deletion already
landed — point the user at it instead of re-attempting.

### 2. List open deletion proposals

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET \
  /contracts/{contract_id}/deletion-proposals
```

Render every proposal whose `status == "proposal"` (the listing
includes accepted ones too — those are read-only history). Show:

- `proposal_id` (truncated for display, full for the accept call)
- `proposer_actor` (the X-Actor at propose time)
- `created_at`
- `rationale`

If there are no open proposals, **stop** — nothing to accept. Point
the user at `/propose-contract-deletion` if they wanted to draft
one.

### 3. Re-fetch the impact block

The impact block was computed at propose time. Things may have
changed since then (sibling proposals landed; part bodies were
edited). Re-propose nothing — just re-fetch by issuing a *fresh*
deletion-proposal preview if the user wants the latest numbers.
The cheap way: GET the contract details and the touching
proposals; the most informative way: re-read the proposal's own
impact via the listing (it stores the snapshot at propose time;
acceptance returns the recomputed impact in its response).

If the user wants the freshest view before accepting:

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET \
  "/contracts/{contract_id}/proposals" \
  | python3 -c "import json, sys; d=json.load(sys.stdin); print('open body proposals:', len(d['proposals']))"
.claude/skills/_shared/scripts/tyr-curl.sh GET \
  "/contracts/{contract_id}/subtype-proposals" \
  | python3 -c "import json, sys; d=json.load(sys.stdin); print('open subtype proposals:', sum(1 for p in d['proposals'] if p['status']=='proposal'))"
.claude/skills/_shared/scripts/tyr-curl.sh GET \
  "/contracts/{contract_id}/endpoint-proposals" \
  | python3 -c "import json, sys; d=json.load(sys.stdin); print('open endpoint proposals:', sum(1 for p in d['proposals'] if p['status']=='proposal'))"
```

### 4. Confirm the target proposal

If multiple open proposals exist, ask which one. If only one,
suggest it as the default. Re-show the rationale before accepting.

If `proposer_actor == TITAN_TYR_ACTOR` and the user hasn't set
`single_operator`, **stop and explain the rule**: the same human
shouldn't both propose and accept a structural change. Options:

1. Have a different operator accept (set `TITAN_TYR_ACTOR` to a
   different value for this run).
2. Pass `?single_operator=true` if this is a one-person setup —
   document the choice in the user reply.

### 5. Final preview

```
About to soft-delete contract `<contract_id>`:
  owner: <owner>
  counterparty: <counterparty>
  subtype/connection_type: <subtype>[/<connection_type>]
  proposed by: <actor>
  rationale: "<rationale>"

After this:
  - GET /contracts/<contract_id> will 404 (use ?include_deleted=true to see).
  - All write endpoints on this contract will 404.
  - GET /contracts and GET /parts/.../contracts will hide the row.
  - GET /contracts/<contract_id>/history?include_deleted=true will still
    surface the full audit trail with two new entries: deletion_proposed
    and deletion_accepted.
  - The same (owner, counterparty, subtype, connection_type) can be
    registered fresh — the uniqueness key is partial-on-live.

Proceed?
```

Wait for an unambiguous yes.

### 6. POST the accept

```sh
.claude/skills/_shared/scripts/tyr-curl.sh POST \
  /contracts/{contract_id}/deletion-proposals/{proposal_id}/accept
```

If using single-operator override:

```sh
.claude/skills/_shared/scripts/tyr-curl.sh POST \
  "/contracts/{contract_id}/deletion-proposals/{proposal_id}/accept?single_operator=true"
```

### 7. Report

On `200`:

```
Soft-deleted. Contract <contract_id>:
  deleted_at: <ts>
  proposer: <proposer_actor or "anonymous">
  acceptor: <accepted_by or "anonymous">
  rationale: "<rationale>"

Impact at accept time:
  parts whose body still references the other endpoint: <list or "none">
  remaining open proposals on this contract: <count>
  audit history entries: <count>

Verify:
  curl -H 'Authorization: Bearer $TITAN_TYR_TOKEN' \
    "$TITAN_TYR_URL/contracts/<contract_id>?include_deleted=true"
```

If the response carries `single_operator_override: true`, surface
it loudly:

> ⚠ Accepted under single-operator override (`?single_operator=true`).
> The two-party rule was bypassed for this deletion. The flag is
> recorded on the proposal row and on the contract's
> `deletion_single_operator_override` column so the bypass is
> visible in the audit trail.

If `proposer_actor` or `accepted_by` is null, surface that — the
rule was unenforceable and that fact should be visible.

If `impact.referenced_in_part_bodies` is non-empty, gently nudge
the user to clean up those references via
`/propose-contract-change` (or part body proposals). Same
tolerance the catalog already has for repurposed contracts: not
blocking, just worth noting.

## Error handling

| Status | Meaning                                                                          | What to do                                                                  |
| ------ | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `404`  | Contract or `proposal_id` doesn't exist, or contract is already soft-deleted     | Re-list proposals; try `GET /contracts/{id}?include_deleted=true` to see if a sibling deletion already landed. |
| `409`  | Proposal is already `accepted` (not in `proposal` status)                         | Re-list to see current state; the proposal is stale.                        |
| `422`  | `proposer_actor == acceptor_actor` without `?single_operator=true`               | Either accept under a different `X-Actor`, or pass `?single_operator=true` for solo setups. |

## Notes

- **Soft, not hard.** The row stays in the database. All read
  endpoints hide it by default; `?include_deleted=true` opts back
  in. All write endpoints 404 — body proposals, subtype shifts,
  endpoint shifts, further deletion proposals all refuse.
- **No undo.** Restoration is not yet built. If the deletion was
  wrong, the path forward is to register a fresh contract with
  the same shape (allowed via the partial-on-live unique key),
  then port the body content via `/propose-contract-change`. The
  history of the deleted contract stays available for audit.
- **History endpoint** picks up two new events on this contract:
  `deletion_proposed` (at propose `created_at`) and
  `deletion_accepted` (at accept `accepted_at`). Both are gated
  behind `?include_deleted=true` since deletion is the kind of
  audit event that warrants an explicit opt-in.
- **Project counts shrink.** `GET /projects/{slug}` and
  `/list-projects` exclude soft-deleted contracts from
  `contract_count` — accepting a deletion will decrement the
  count by one if the contract was tagged.
