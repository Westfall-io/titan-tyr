---
name: propose-contract-deletion
description: Propose a soft-delete of an existing contract — e.g. "this binding was registered against the wrong endpoint and should be retired", "this contract was an experiment that didn't pan out". Use when the user wants to remove a contract from the catalog without losing the audit trail. Walks the user through a rationale + impact preview (parts whose body references the other endpoint, count of open sibling proposals that would lose their target, count of accepted history entries on the contract), then POSTs to /contracts/{contract_id}/deletion-proposals. Does NOT accept the proposal — acceptance is the deliberate counterpart via /accept-contract-deletion.
---

# propose-contract-deletion

You are drafting a proposed **deletion** for an existing contract.
Acceptance soft-deletes the row (sets `deleted_at` plus the proposer
/ acceptor / rationale columns); the row stays in the database for
audit and is hidden from default reads. The proposal row itself
persists so the audit trail reads back as
`registered → … → deletion_proposed → deletion_accepted`.

This skill **creates the proposal** and never accepts it. Acceptance
goes through `/accept-contract-deletion` and **must be performed by
a different X-Actor** (proposer-doesn't-accept rule, with
`?single_operator=true` as an explicit override for solo setups).

Soft-delete is the only deletion path. There is no hard-delete
endpoint. If the deletion turns out to be wrong, the row can still
be inspected via `?include_deleted=true`; restoration is not yet
built (a future `/contracts/{id}/restoration-proposals` would undo).

## Server location

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |
| `TITAN_TYR_ACTOR` | no       | Identity for the X-Actor header. If unset, the proposal records `null` and the two-party rule cannot be enforced — warn the user that any acceptor will be allowed. |

If `TITAN_TYR_URL` is unset, **stop and tell the user**. Don't guess.

## Workflow

### 1. Confirm reachability

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET /templates/software \
  -o /dev/null
```

`200` → continue. `401` → wrong token, stop.

### 2. Resolve the contract

Contracts are addressed by `contract_id` (UUID). Branch on what the
user gave you:

- **They gave a `contract_id`.** Use it directly.
- **They gave two part names.** Search:

  ```sh
  .claude/skills/_shared/scripts/tyr-curl.sh GET \
    "/contracts?owner={a}&counterparty={b}"
  ```

  If both directions might exist, ask which the user means. Surface
  the current `subtype` and (if connection) `connection_type`.

- **They gave one part name.** List touching contracts:

  ```sh
  .claude/skills/_shared/scripts/tyr-curl.sh GET \
    "/parts/{name}/contracts"
  ```

  Show the user each row with its current endpoints + subtype, and
  ask which contract.

Then GET the resolved contract to confirm:

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET /contracts/{contract_id}
```

`404` → either the id is wrong or the contract is already
soft-deleted. Re-check with `?include_deleted=true`. If it is
soft-deleted, **stop** — there is nothing to propose; the row is
already gone.

Surface its current `(owner, counterparty, subtype, connection_type)`
to the user before they confirm the deletion.

### 3. Get the rationale

Ask the user *why* the contract should be retired. The rationale is
required (1-2000 chars) and lands in the proposal record (and
ultimately on the soft-deleted contract row as
`deletion_rationale`). A good rationale describes the cause —
"registered against the legacy service ahead of the cutover; the
real binding now points at the new prod service" — not just "wrong".

### 4. POST the proposal

Build the JSON body:

```json
{"rationale": "..."}
```

POST it:

```sh
.claude/skills/_shared/scripts/tyr-curl.sh POST \
  /contracts/{contract_id}/deletion-proposals \
  --data @.scratch/contract-deletion.json
```

The response carries `proposal_id` plus an `impact` block:

```json
{
  "proposal_id": "...",
  "contract_id": "...",
  "rationale": "...",
  "proposer_actor": "...",
  "status": "proposal",
  "impact": {
    "referenced_in_part_bodies": ["part-a"],
    "referenced_in_open_proposals": 0,
    "active_history_entries": 3
  }
}
```

### 5. Read the impact block with the user

Walk through it before stopping:

- **`referenced_in_part_bodies`** lists endpoint parts whose latest
  body mentions the *other* endpoint by name (typical "Connections"
  section reference). On accept, those references will dangle —
  same tolerance the catalog already has when a contract is
  repurposed. If the user wants a clean handoff, suggest filing
  `/propose-contract-change` (or part body proposals) on those
  parts to remove the reference *before* accepting. Soft-warn only;
  the deletion is not blocked by a non-empty list.
- **`referenced_in_open_proposals`** counts open propose-level rows
  on this contract (body, subtype, endpoint, sibling deletion
  proposals). Accept will leave those proposals stranded — they
  cannot be accepted because the contract becomes 404 to writes.
  Tell the user; if any need to land first, accept them before
  this deletion.
- **`active_history_entries`** is the count of accepted history
  events on the contract. Surfaced so the user can see what audit
  trail they're soft-deleting (the history itself stays accessible
  via `?include_deleted=true`).

### 6. Stop here

Do **not** call the accept endpoint. Tell the user the
`proposal_id` and that acceptance goes through
`/accept-contract-deletion` (must be a different `X-Actor`, or
pass `?single_operator=true` for solo setups).

## Error handling

| Status | Meaning                                                           | What to do                                                        |
| ------ | ----------------------------------------------------------------- | ----------------------------------------------------------------- |
| `404`  | `contract_id` doesn't exist, or the contract is already soft-deleted | Re-check the id; try `?include_deleted=true` on the GET to confirm. |
| `422`  | rationale missing or out of range                                  | Re-prompt for a rationale of 1-2000 chars.                         |

## Notes

- **Soft delete preserves audit.** Accepted deletion sets
  `deleted_at` plus `deleted_by_proposer_actor` /
  `deleted_by_acceptor_actor` / `deletion_rationale`. The row is
  hidden from default reads and refused by all write endpoints
  (PUT, body proposals, subtype/endpoint/deletion proposals all
  return 404), but `GET /contracts/{id}?include_deleted=true` and
  `GET /contracts/{id}/history?include_deleted=true` still surface
  the row and its full audit trail.
- **Re-registration is allowed.** The uniqueness key on
  `(owner, counterparty, subtype, connection_type)` is partial-on-
  live: soft-deleted rows do not block a fresh POST `/contracts`
  with the same shape. The new row gets its own contract_id; both
  rows are visible via `?include_deleted=true`.
- **Two-party rule is structural.** The `X-Actor` header is the
  signal until real auth lands. Solo setups override the rule on
  accept via `?single_operator=true` — this skill records the
  proposer; the accept skill checks the acceptor.
- **Impact is informational.** A non-empty
  `referenced_in_part_bodies` or `referenced_in_open_proposals`
  does not block the proposal or the accept. The catalog tolerates
  dangling name references the same way it does when a contract
  is repurposed.
