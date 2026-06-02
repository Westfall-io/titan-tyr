---
name: reassign-contract-owner
description: Reassign ownership of a registered contract to a new actor. Wraps PUT /contracts/{id}/owner — single write, no two-party rule, overwrite allowed (#119).
---

# reassign-contract-owner

You are reassigning the `owner_actor` of a contract already
registered with titan-tyr. The endpoint is
`PUT /contracts/{contract_id}/owner`. Single write: no two-party
handshake, no propose/accept dance. Overwrite is allowed — there is
no first-write-wins semantic (#119 superseded the legacy backfill
behavior).

The reassigning actor (`X-Actor` derived from your token) is
captured in the response as `reassigned_by_actor` for the audit
trail. The previous owner is captured as `previous_owner_actor`.

## Server location

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | yes      | Bearer per-caller token (issue via `/issue-auth-token`). |

If `TITAN_TYR_URL` is unset, **stop and tell the user**. Don't guess.

## Workflow

### 1. Confirm reachability

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

`200` → continue. `401` → wrong token, stop.

### 2. Resolve the contract

Same shape as `/update-contract` step 2 — addressed by `contract_id`
(UUID). If the user gave two part names, search via
`?owner=&counterparty=`; if one part, list touching contracts via
`/parts/{name}/contracts`. Then GET the resolved contract to confirm
current `owner_actor`:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}"
```

Surface the current `owner_actor` so the user can confirm the
starting state. `404` → contract not found.

### 3. Get the new owner + rationale

Ask the user:
- **New owner slug** (1–64 chars, valid slug shape).
- **Rationale** (1–2000 chars). Required field. Captures the *why*
  for the audit trail — "shifting responsibility from <X> to <Y> as
  part of <handoff>," "correcting misattribution from earlier
  handoff token," etc.

### 4. POST the reassignment

```sh
curl -fsS -X PUT \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"new_owner_actor": "<slug>", "rationale": "<text>"}' \
  "$TITAN_TYR_URL/contracts/{contract_id}/owner"
```

`200` → success; response carries `previous_owner_actor`,
`new_owner_actor`, `reassigned_by_actor`, `reassigned_at`,
`rationale`. `404` → contract not found. `422` → missing/invalid
rationale or `new_owner_actor`.

### 5. Report

```
Reassigned ownership of contract <contract_id>:
  owner / counterparty: <owner> → <counterparty>
  subtype: <subtype>[/<connection_type>]
  previous owner_actor: <previous>
  new owner_actor:      <new>
  reassigned by:        <your X-Actor>
  rationale:            <echo>
  at:                   <iso8601>

(Body / version / endpoints unchanged. Reassignment does not bump
the contract's semver — it's a metadata mutation.)
```

## Notes

- **No two-party rule.** Reassignment is a single-actor write. The
  reassigning actor's identity (derived from your token) is captured
  alongside the new owner so the audit trail records both sides of
  the handoff.
- **Overwrite is allowed.** This is the post-#119 behavior. The old
  first-write-wins semantic (which only let `PUT /contracts/{id}`
  claim a NULL `owner_actor`) is gone. You can reassign ownership
  any number of times.
- **Body version is not bumped.** Reassignment is a metadata
  mutation, parallel to subtype/endpoint shifts. Reads return the
  same body version as before. Per-version `proposer_actor` /
  `acceptor_actor` for content changes still live on the
  proposal/accept history rows.
- **`/update-contract` is the wrong path.** That skill handles
  project-tag changes and explicitly does NOT touch `owner_actor`
  post-#119. If the user wants to reassign ownership, you're in the
  right skill.
