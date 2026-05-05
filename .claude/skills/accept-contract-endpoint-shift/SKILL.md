---
name: accept-contract-endpoint-shift
description: Accept an open contract endpoint-shift proposal — promote it from `proposal` to `accepted` and re-point one or both endpoints on the contract row. Use when the user wants to land a previously-proposed endpoint shift — e.g. "accept the endpoint shift on contract abc123", "promote the swap to the new prod owner". Lists open endpoint proposals on the contract, confirms the chosen one, and POSTs to /contracts/{contract_id}/endpoint-proposals/{proposal_id}/accept. Enforces the proposer-doesn't-accept rule via the X-Actor header (with `?single_operator=true` as the documented override). Acceptance does NOT mutate the body or version — only the endpoint FK columns change.
---

# accept-contract-endpoint-shift

You are promoting a previously-drafted contract endpoint shift to
`accepted`. Acceptance is the deliberate counterpart to
`/propose-contract-endpoint-shift`: the propose skill drafts and
submits; this skill lands.

This is the **only mutating step** in the contract endpoint-shift
flow. Treat the final POST as load-bearing: do not run it without an
explicit user confirmation on the exact proposal about to land, and
**do not run it under the same `X-Actor` as the proposer**
(proposer-doesn't-accept rule, with `?single_operator=true` as the
documented override).

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
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

Then verify the contract exists:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}"
```

`404` → stop.

### 2. List open endpoint proposals

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}/endpoint-proposals"
```

Render every proposal whose `status == "proposal"` (the listing
includes accepted ones too — those are read-only history). Show:

- `proposal_id` (truncated for display, full for the accept call)
- `current_owner_at_propose` / `current_counterparty_at_propose`
- `new_owner` / `new_counterparty` (either may be `null` for a
  one-sided shift)
- `proposer_actor` (the X-Actor at propose time)
- `created_at`
- `rationale`

If there are no open proposals, **stop** — nothing to accept. Point
the user at `/propose-contract-endpoint-shift` if they wanted to
draft one.

### 3. Confirm the target proposal

If multiple open proposals exist, ask which one. If only one, suggest
it as the default. Re-show the rationale before accepting; the impact
may have changed since propose time as endpoint subtypes shifted or
new contracts were created.

If `proposer_actor == TITAN_TYR_ACTOR` and the user hasn't set
`single_operator`, **stop and explain the rule**: the same human
shouldn't both propose and accept a structural change. Options:

1. Have a different operator accept (set `TITAN_TYR_ACTOR` to a
   different value for this run).
2. Pass `?single_operator=true` if this is a one-person setup —
   document the choice in the user reply.

### 4. Final preview

```
About to accept contract endpoint shift on `<contract_id>`:
  owner: <current_owner> → <new_owner_or_unchanged>
  counterparty: <current_counterparty> → <new_counterparty_or_unchanged>
  subtype/connection_type: unchanged
  proposed by: <actor>
  rationale: "<rationale>"

After this, GET /contracts/<contract_id> will return the new
endpoint(s). The body and version are unchanged. Proceed?
```

Wait for an unambiguous yes.

### 5. POST the accept

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  "$TITAN_TYR_URL/contracts/{contract_id}/endpoint-proposals/{proposal_id}/accept"
```

If using single-operator override:

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  "$TITAN_TYR_URL/contracts/{contract_id}/endpoint-proposals/{proposal_id}/accept?single_operator=true"
```

### 6. Report

On `200`:

```
Accepted. Contract <contract_id> endpoints are now:
  owner: <shifted_to_owner> (was <shifted_from_owner>)
  counterparty: <shifted_to_counterparty> (was <shifted_from_counterparty>)
Body and version are unchanged.
Proposer: <proposer_actor or "anonymous">. Acceptor: <accepted_by or "anonymous">.

Verify:
  curl -H 'Authorization: Bearer $TITAN_TYR_TOKEN' $TITAN_TYR_URL/contracts/<contract_id>
```

If the response carries `single_operator_override: true`, surface it
loudly in the summary:

> ⚠ Accepted under single-operator override (`?single_operator=true`).
> The two-party rule was bypassed for this shift. The flag is
> recorded on the proposal row so the bypass is visible in the
> audit trail.

If `proposer_actor` or `accepted_by` is null, surface that — the
rule was unenforceable and that fact should be visible.

## Error handling

| Status | Meaning                                                                          | What to do                                                                  |
| ------ | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `404`  | Contract or `proposal_id` doesn't exist                                          | Re-list proposals; check the contract id.                                   |
| `409`  | Proposal already accepted, no-op (concurrent shift landed first), endpoint part deleted, or a colliding contract now exists at the proposed endpoint pair | Re-list to see current state; the proposal may be stale or need re-filing. |
| `422`  | Source/target rule no longer satisfied (endpoint subtype may have shifted), self-loop, or `proposer_actor == acceptor_actor` without override | Investigate: which endpoint subtype changed? Re-propose, or shift the endpoint subtype first. |

## Notes

- **Body and version are not mutated.** Only `contracts.owner_part_id`
  / `contracts.counterparty_part_id`,
  `contracts.endpoint_shifted_from_owner` /
  `contracts.endpoint_shifted_from_counterparty`, and
  `contracts.endpoint_shifted_at` change.
- **No undo.** Acceptance is reversible only by proposing the
  reverse shift (and accepting that). Treat acceptance as
  load-bearing.
- **History endpoint** picks up the shift event automatically:
  `GET /contracts/<contract_id>/history` returns one entry per body
  bump *and* one per accepted shift, distinguished by the `kind`
  field (`body_bump`, `subtype_shift`, or `endpoint_shift`).
  Soft-deletion events (`deletion_proposed`, `deletion_accepted`,
  v0.26.0+, #69) only surface with `?include_deleted=true`.
- **Acceptance re-validates.** Source/target rule (does the new
  endpoint's subtype satisfy the contract's binding/connection
  rule?) and uniqueness (does the new pair collide with an existing
  contract?) are re-checked at accept time. A proposal that passed
  at propose time may fail on accept if the surrounding state has
  shifted; re-propose once the underlying state is stable.
- **One-sided shifts** leave the unchanged side's bookkeeping col
  NULL. The audit trail records *what changed*, not the entire
  pre-shift state.
