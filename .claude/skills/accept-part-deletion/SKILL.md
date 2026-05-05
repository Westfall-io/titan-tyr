---
name: accept-part-deletion
description: Accept an open part deletion proposal — soft-delete the part row, optionally cascading to touching contracts. Use when a human operator wants to land a previously-proposed part deletion. Lists open deletion proposals on the part, re-shows the impact block (including the touching-contracts list that drives cascade-vs-block), and POSTs to /parts/{name}/deletion-proposals/{proposal_id}/accept. Stricter than ordinary two-party — the acceptor X-Actor must be a HUMAN (not in the agent allowlist), and ?single_operator=true is forbidden. ?cascade=true is required to land if touching_contracts is non-empty; cascade soft-deletes those contracts in the same transaction.
---

# accept-part-deletion

You are promoting a previously-drafted part deletion proposal to
`accepted`. Acceptance soft-deletes the part row (`deleted_at`,
proposer / acceptor / rationale columns) and, if `?cascade=true`,
also soft-deletes every live contract touching the part with the
same actors and a rationale prefixed `cascaded from
/propose-part-deletion: ...`.

This is the **only mutating step** in the part deletion flow and
the most destructive single operation in titan-tyr — it can wipe
a node and a whole star of edges in one transaction. Treat it
accordingly.

## Human-confirmation rule (structural; not optional)

Part deletion enforces a stricter rule than other accepts:

1. The acceptor X-Actor must be set AND must NOT be in the live
   `agent_actors` allowlist (DB-backed since #78; check with
   `GET /agent-actors` for the current set — typically includes
   `titan-tyr`, `archaedas`, `mimiron`). Two agents bouncing the
   handshake doesn't satisfy this — a human operator must confirm.
2. The standard two-party rule still applies: proposer X-Actor ≠
   acceptor X-Actor.
3. `?single_operator=true` is **forbidden** (422). The whole point
   is human confirmation; the bypass defeats it.

If you are running as an agent (your own X-Actor is `titan-tyr`),
you **cannot accept this proposal yourself**. Stop and tell the
user explicitly: "I can propose deletions, but acceptance requires
a human operator to set their own `X-Actor` (e.g.
`alice@example.com`) and run the accept call themselves."

If the user has set `TITAN_TYR_ACTOR` to something that looks like
an agent identity (matches the allowlist), surface the rule and
ask them to override `TITAN_TYR_ACTOR` for the accept.

## Server location

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |
| `TITAN_TYR_ACTOR` | yes (here) | The acceptor identity. **Must be a human's identifier** — anything not in the live `agent_actors` allowlist (`GET /agent-actors`). The accept will 403 if this is e.g. `titan-tyr` / `archaedas` / `mimiron`. |

If `TITAN_TYR_URL` is unset, **stop and tell the user**.

## Workflow

### 1. Confirm reachability and target part

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET /templates/software \
  -o /dev/null
```

Then verify the part is still live:

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET /parts/{name}
```

`404` → the part is gone. Either the slug is wrong or someone
else accepted a deletion in the meantime. Try
`?include_deleted=true`; if it shows up, the deletion already
landed — point the user at it instead of re-attempting.

### 2. List open deletion proposals

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET \
  /parts/{name}/deletion-proposals
```

Render every proposal whose `status == "proposal"` (the listing
includes accepted ones too — those are read-only history). Show:

- `proposal_id` (truncated for display, full for the accept call)
- `proposer_actor` (the X-Actor at propose time)
- `created_at`
- `rationale`

If there are no open proposals, **stop** — nothing to accept. Point
the user at `/propose-part-deletion` if they wanted to draft one.

### 3. Re-fetch the impact block

The impact block at propose time may be stale by now (sibling
contracts registered, part bodies edited). Re-compute the
touching-contracts count via:

```sh
.claude/skills/_shared/scripts/tyr-curl.sh GET \
  /parts/{name}/contracts \
  | python3 -c "import json, sys; d=json.load(sys.stdin); print('touching contracts:', len(d['results']))"
```

If non-zero, the user must opt into `?cascade=true`. Surface this
explicitly.

### 4. Confirm the target proposal + check the agent rule

Pre-flight the agent rule before you preview:

```sh
case "$TITAN_TYR_ACTOR" in
  titan-tyr|titan-archaedas|"")
    echo "STOP: TITAN_TYR_ACTOR ($TITAN_TYR_ACTOR) is an agent or unset; part deletion requires a human acceptor"
    exit 1
    ;;
esac
```

If `proposer_actor == TITAN_TYR_ACTOR`, **stop and explain**: the
two-party rule still applies. Ask the user to either:

1. Have a different human accept (e.g. a teammate sets their own
   `TITAN_TYR_ACTOR`).
2. If they're truly the only operator, file the proposal under a
   different identity and accept under their human one. (No
   `single_operator` bypass exists for part deletion.)

### 5. Final preview

```
About to soft-delete part `<part_name>`:
  subtype: <subtype>
  proposed by: <proposer_actor>
  rationale: "<rationale>"
  touching contracts: <N> live contract(s)
  cascade: <true | false — explicit user choice>

After this:
  - GET /parts/<name> will 404 (use ?include_deleted=true to see).
  - All write endpoints on this part will 404.
  - /find-part and listings will hide the row.
  - The same name can be re-registered fresh — uniqueness is
    partial-on-live.
  - GET /parts/<name>/history?include_deleted=true will surface
    the full audit trail with deletion_proposed and deletion_accepted
    entries.
[if cascade]
  - <N> touching contract(s) will also be soft-deleted with this
    proposer/acceptor and a rationale prefixed
    "cascaded from /propose-part-deletion: ...".
[if not cascade and N > 0]
  - This will 422. The touching contracts must be deleted first
    (via /propose-contract-deletion + /accept-contract-deletion)
    or you must re-run with ?cascade=true.

Proceed?
```

Wait for an unambiguous yes from the human operator.

### 6. POST the accept

Pick the URL based on whether cascade is needed:

```sh
# Clean delete (no touching contracts):
.claude/skills/_shared/scripts/tyr-curl.sh POST \
  /parts/{name}/deletion-proposals/{proposal_id}/accept

# With cascade (touching contracts present):
.claude/skills/_shared/scripts/tyr-curl.sh POST \
  "/parts/{name}/deletion-proposals/{proposal_id}/accept?cascade=true"
```

### 7. Report

On `200`:

```
Soft-deleted. Part <part_name>:
  deleted_at: <ts>
  proposer: <proposer_actor>
  acceptor: <accepted_by>
  rationale: "<rationale>"
  cascade: <true | false>
[if cascaded_contract_ids non-empty]
  cascaded contracts: <N>
    - <contract_id_1>
    - <contract_id_2>
    - ...

Verify:
  curl -H 'Authorization: Bearer $TITAN_TYR_TOKEN' \
    "$TITAN_TYR_URL/parts/<name>?include_deleted=true"
```

If `impact.referenced_in_part_bodies` is non-empty, gently nudge
the user to clean up those references via `/update-part`. Same
tolerance the catalog already has for renamed parts: not blocking,
just worth noting.

## Error handling

| Status | Meaning                                                                          | What to do                                                                  |
| ------ | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `404`  | Part or `proposal_id` doesn't exist, or the part is already soft-deleted         | Re-list proposals; try `GET /parts/{name}?include_deleted=true`.            |
| `409`  | Proposal is already `accepted` (not in `proposal` status)                         | Re-list to see current state; the proposal is stale.                        |
| `403`  | Acceptor X-Actor is in the known-agent allowlist                                  | Re-run with a human X-Actor.                                                |
| `422` (proposer-doesn't-accept) | Same X-Actor on both sides without override        | Have a different human accept. (No `single_operator` bypass available.)     |
| `422` (touching contracts)      | Touching live contracts present, `?cascade=true` not passed | Either delete them first or re-run with `?cascade=true`.                    |
| `422` (single_operator)         | `?single_operator=true` was passed                | Drop the flag; part deletion requires a true two-party handshake.           |
| `422` (anonymous acceptor)      | No `X-Actor` header on the accept                 | Set `TITAN_TYR_ACTOR` to a human identity and re-run.                       |

## Notes

- **Soft, not hard.** The row stays in the database. All read
  endpoints hide it by default; `?include_deleted=true` opts back
  in. All write endpoints 404. The same is true for cascaded
  contracts — they survive in the DB with their own audit trail.
- **No undo.** Restoration is not yet built. If the deletion was
  wrong, the path forward is to register a fresh part with the
  same name (allowed via the partial-on-live unique key), then
  re-stamp the body via `/update-part`. Cascaded contracts stay
  soft-deleted; you'd need to re-register each one too. The
  history of the deleted part stays available for audit.
- **History endpoint** picks up two new events on this part:
  `deletion_proposed` (at propose `created_at`) and
  `deletion_accepted` (at accept `accepted_at`). Both gated
  behind `?include_deleted=true`. The same kinds appear on
  `/contracts/{id}/history` for cascaded contracts (since each
  cascaded contract has its `deleted_at` stamped, but no
  `contract_deletion_proposal` row — the audit trail there is
  the matching `deleted_at` timestamp + the rationale prefix).
- **Project counts shrink.** Both `part_count` and
  `contract_count` on `/projects/{slug}` exclude soft-deleted
  rows — accepting a part deletion (with cascade) can decrement
  both counts.
