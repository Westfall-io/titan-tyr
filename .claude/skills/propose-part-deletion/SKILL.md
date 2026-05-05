---
name: propose-part-deletion
description: Propose a soft-delete of an existing part — e.g. "this throwaway part from the smoke tests should be retired", "this experiment didn't pan out". Use when the user wants to remove a part from the catalog without losing the audit trail. Walks the user through a rationale + impact preview (touching contracts that would block-or-cascade, parts whose body references this one, count of accepted history entries), then POSTs to /parts/{name}/deletion-proposals. Does NOT accept the proposal — acceptance is the deliberate counterpart via /accept-part-deletion. Distinct from contract deletion (#69's `/propose-contract-deletion`) which retires edges, not nodes.
---

# propose-part-deletion

You are drafting a proposed **deletion** for an existing part.
Acceptance soft-deletes the row (sets `deleted_at` plus the proposer
/ acceptor / rationale columns); the row stays in the database for
audit and is hidden from default reads. The proposal row itself
persists so the audit trail reads back as
`registered → … → deletion_proposed → deletion_accepted`.

This skill **creates the proposal** and never accepts it. Acceptance
goes through `/accept-part-deletion` and is **stricter than ordinary
two-party**: the acceptor X-Actor must be a human (not in the
known-agent allowlist), and `?single_operator=true` is forbidden
on accept. See the human-confirmation note below.

There is no hard-delete endpoint. If the deletion turns out to be
wrong, the row can still be inspected via `?include_deleted=true`;
restoration is not yet built.

## Server location

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |
| `TITAN_TYR_ACTOR` | no       | Identity for the X-Actor header. If unset, the proposal records `null` and the two-party rule cannot be enforced — warn the user that any acceptor will be allowed (subject to the human-confirmation rule on accept). |

If `TITAN_TYR_URL` is unset, **stop and tell the user**. Don't guess.

## Workflow

### 1. Confirm reachability

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET /templates/software \
  -o /dev/null
```

`200` → continue. `401` → wrong token, stop.

### 2. Resolve the part

Parts are addressed by `name` slug. Confirm it exists:

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET /parts/{name}
```

`404` → either the slug is wrong or the part is already
soft-deleted. Re-check with `?include_deleted=true`. If it is
soft-deleted, **stop** — there is nothing to propose; the row is
already gone.

If the user gave a colloquial label rather than a slug, run
`/find-part` first to resolve, then bring the canonical slug here.

Surface the part's current `(name, subtype, project)` to the user
before they confirm the deletion.

### 3. Get the rationale

Ask the user *why* the part should be retired. The rationale is
required (1-2000 chars) and lands in the proposal record (and
ultimately on the soft-deleted row as `deletion_rationale`). A good
rationale describes the cause — "throwaway part from #63 helper
smoke tests; never had production use" — not just "delete".

### 4. POST the proposal

Build the JSON body:

```json
{"rationale": "..."}
```

POST it:

```sh
.claude/skills/_shared/scripts/tyr-curl.sh POST \
  /parts/{name}/deletion-proposals \
  --data @.scratch/part-deletion.json
```

The response carries `proposal_id` plus an `impact` block:

```json
{
  "proposal_id": "...",
  "part_name": "...",
  "rationale": "...",
  "proposer_actor": "...",
  "status": "proposal",
  "impact": {
    "touching_contracts": [
      {"contract_id": "...", "owner": "...", "counterparty": "...", "subtype": "...", "connection_type": null}
    ],
    "referenced_in_part_bodies": ["other-part"],
    "active_history_entries": 5
  }
}
```

### 5. Read the impact block with the user

This is where part deletion differs structurally from contract
deletion: a part is a node, contracts are edges. Walk through the
block before stopping:

- **`touching_contracts`** — every live contract whose owner or
  counterparty is this part. **This is the cascade-vs-block driver
  on accept.** Tell the user explicitly:
  - If the list is empty, accept will run cleanly with no extra
    flag.
  - If the list is non-empty, accept will **422 hard-block** unless
    the user passes `?cascade=true`. Cascade soft-deletes every
    listed contract in the same transaction (with a rationale
    prefixed `"cascaded from /propose-part-deletion: ..."`).
  - The other path: file `/propose-contract-deletion` and
    `/accept-contract-deletion` for each touching contract first,
    then accept the part deletion with no cascade. More legible
    audit trail per-contract; more work per-row.
- **`referenced_in_part_bodies`** — other parts whose latest body
  mentions THIS part by whole-token slug. Soft-warn only. After
  accept, those references will dangle — same tolerance the
  catalog already has when a part is renamed via
  `/propose-part-name-shift`. If the user wants a clean handoff,
  suggest filing `/update-part` on those parts to remove the
  reference *before* accepting.
- **`active_history_entries`** — count of accepted history events
  on the part (body bumps + subtype shifts + name shifts). Surfaced
  so the user can see what audit trail they're soft-deleting (the
  history itself stays accessible via `?include_deleted=true`).

### 6. Stop here

Do **not** call the accept endpoint. Tell the user the
`proposal_id` and that acceptance goes through
`/accept-part-deletion`. Spell out the human-confirmation rule
explicitly so they know what to expect:

> Acceptance requires:
> 1. A different `X-Actor` than this proposer (standard two-party rule), AND
> 2. The acceptor X-Actor must be a **human** — not in the agent
>    allowlist (default: `titan-tyr`, `titan-archaedas`). Two
>    agents bouncing the handshake won't satisfy the rule.
> 3. `?single_operator=true` is **forbidden** on this accept.
> If the touching_contracts list above is non-empty, the acceptor
> will also need to pass `?cascade=true` to land the deletion.

## Error handling

| Status | Meaning                                                    | What to do                                                        |
| ------ | ---------------------------------------------------------- | ----------------------------------------------------------------- |
| `404`  | `name` doesn't exist, or the part is already soft-deleted | Re-check the slug; try `?include_deleted=true` on the GET to confirm. |
| `422`  | rationale missing or out of range                          | Re-prompt for a rationale of 1-2000 chars.                         |

## Notes

- **Soft delete preserves audit.** Accepted deletion sets
  `deleted_at` plus `deleted_by_proposer_actor` /
  `deleted_by_acceptor_actor` / `deletion_rationale` on `parts`.
  The row is hidden from default reads and refused by all write
  endpoints (PUT, subtype shifts, name shifts, deletion proposals
  all return 404), but `GET /parts/{name}?include_deleted=true`
  and `GET /parts/{name}/history?include_deleted=true` still
  surface the row and its full audit trail.
- **Re-registration is allowed.** The uniqueness key on
  `parts.name` is partial-on-live: soft-deleted rows do not block
  a fresh POST `/parts` with the same slug. The new row gets its
  own id; both rows are visible via `?include_deleted=true`.
- **Cascade is single-row-deep.** A part deletion cascades only to
  the contracts whose owner or counterparty is this part. It does
  not chain further (no part-to-part dependency edges that warrant
  chaining today).
- **Human-confirmation rule is structural.** Part deletion is
  destructive and can wipe a whole star of contracts on accept;
  the rule exists so two agents bouncing a handshake can't trigger
  that without a human in the loop. If the user is operating solo,
  they can still run this skill (as an agent or under their own
  email) — the human-confirmation only kicks in on the accept side.
