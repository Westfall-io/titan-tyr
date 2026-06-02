---
name: update-contract
description: Update soft metadata on an existing contract (project tag). Does NOT change body — use /propose-contract-change. Does NOT change ownership — use PUT /contracts/{id}/owner (#119).
---

# update-contract

> **POST-#119 NOTE.** This skill body still describes the legacy
> `owner_actor` first-write-wins backfill behavior on `PUT /contracts/{id}`.
> That semantic was removed: `PUT /contracts/{id}` no longer touches
> `owner_actor` at all. To reassign ownership, use the dedicated
> `PUT /contracts/{contract_id}/owner` endpoint (single write, no
> two-party rule, overwrite allowed). The rest of this skill (project
> tag PATCH semantics) is still accurate. Full body rewrite pending.

You are PUT-ing soft metadata on an existing contract. This is the
parallel to `/update-part` for contracts, scoped tightly: the only
field this PUT touches today is `project` (optional tag). Ownership
changes go through `PUT /contracts/{contract_id}/owner` (added in
#119).

Use cases:
- **Tag a contract to a project.** The `project` field on
  `POST /contracts` was added in v0.18.0 (#44); contracts registered
  before that are stuck at `project: null` until updated through
  this surface.
- **Re-project a contract.** Move it between projects, or clear the
  tag back to unprojected.
- **Backfill `owner_actor`.** Send the original creator's
  `X-Actor` to claim a row that was registered before X-Actor
  existed (or before the registrant set it). First-write-wins:
  once `owner_actor` is set, this PUT silently ignores X-Actor
  for that field — no identity-spoofing of attributed rows.

This skill **does not** propose body changes, shift subtypes, shift
endpoints, or rename anything. Each of those has its own dedicated
flow.

## Server location

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer per-caller token (issue via `/issue-auth-token`). Required.             |
| `TITAN_TYR_ACTOR` | no       | Identity for the X-Actor header. Used for the `owner_actor` backfill described below. If unset and the row is already attributed, the PUT still works — X-Actor only affects `owner_actor` when the field is currently `null`. |

If `TITAN_TYR_URL` is unset, **stop and tell the user**.

## Workflow

### 1. Confirm reachability

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

`200` → continue. `401` → wrong token, stop.

### 2. Resolve the contract

Contracts are addressed by `contract_id` (UUID). Branch on what the
user gave you:

- **They gave a `contract_id`.** Use it directly.
- **They gave two part names.** Search:

  ```sh
  curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
    "$TITAN_TYR_URL/contracts?owner={a}&counterparty={b}"
  ```

  If multiple subtypes exist between the pair, ask which one (#42's
  widened uniqueness key permits one of each subtype/connection
  variant per direction). Pick the row's `contract_id`.
- **They gave one part name.** List touching contracts:

  ```sh
  curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
    "$TITAN_TYR_URL/parts/{name}/contracts"
  ```

  Show the user each row with its current endpoints + subtype +
  project. Ask which contract.

Then GET the resolved contract to confirm:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}"
```

Surface its current `project` and `owner_actor` so the user can
see the starting state.

### 3. Decide what's changing

PATCH semantics on `project`:

| Field     | Omitted from body         | `"project": "<slug>"`                        | `"project": null`                |
| --------- | ------------------------- | -------------------------------------------- | -------------------------------- |
| `project` | Existing tag unchanged.   | Reassigns to that project (422 if unknown).  | Clears tag (move to unprojected). |

If the user wants to claim attribution on a `owner_actor: null`
row, no payload field is needed — just send `X-Actor` on the request.
The backfill is automatic and one-shot. If `owner_actor` is
already set, this PUT will not touch it (no error; the field is
silently left alone).

If the user wants neither — no project change, no actor backfill —
**stop**. There's nothing to do; the PUT would be a no-op on the
data side and that's not a useful call to make.

### 4. Validate the project slug

If setting `project` to a value, pre-flight that the project exists:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/projects/{slug}" -o /dev/null
```

`404` → stop, tell the user the slug doesn't exist. Suggest
`/list-projects` to discover valid slugs, or `/register-project` to
create the project first.

### 5. POST the update

```sh
curl -fsS -X PUT \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  --data '{"project": "<slug>"}' \
  "$TITAN_TYR_URL/contracts/{contract_id}"
```

Or to clear the project tag:

```sh
  --data '{"project": null}' \
```

Or to backfill `owner_actor` only (no project change):

```sh
  --data '{}' \
```

(Empty body is valid; the X-Actor header is what carries the claim.)

The response is the full persisted row (same shape as
`GET /contracts/{contract_id}` — see #47), so no follow-up GET is
needed to verify the change landed.

### 6. Report

On `200`:

```
Updated contract <contract_id>:
  owner / counterparty: <owner> → <counterparty>
  subtype: <subtype>[/<connection_type>]
  project: <new project tag, or "unprojected">
  owner_actor: <echoed value> [if backfilled, note "claimed via X-Actor on this PUT"]
  version: <unchanged>

Verify (optional, the response above is authoritative):
  curl -H 'Authorization: Bearer $TITAN_TYR_TOKEN' $TITAN_TYR_URL/contracts/<contract_id>
```

If `X-Actor` was sent and `owner_actor` was previously `null`,
note that the claim landed (compare the `owner_actor` in the
response to the value the user sent). If `owner_actor` was
already set, mention that the X-Actor was ignored for that field
(the backfill is one-shot).

## Error handling

| Status | Meaning                                                                          | What to do                                                                                |
| ------ | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `404`  | Contract id doesn't exist                                                        | Re-resolve via `?owner=&counterparty=` or `/parts/{name}/contracts`.                      |
| `422`  | `project` slug is malformed (uppercase, dots, etc.) or references an unknown project | Re-prompt; verify with `/list-projects` or `/register-project`.                       |

## Notes

- **Body / version / subtype / connection_type / endpoints don't
  belong here.** Use the dedicated propose/accept flows for those:
  `/propose-contract-change` (body), `/propose-contract-subtype-shift`
  (subtype + connection_type), `/propose-contract-endpoint-shift`
  (endpoints), `/accept-contract-proposal` /
  `/accept-contract-subtype-shift` /
  `/accept-contract-endpoint-shift` for acceptance. This PUT is for
  metadata that has no semantic effect on the agreement.
- **`owner_actor` backfill is first-write-wins.** Once set,
  this PUT will not change it. The flag exists so original
  registrants of pre-X-Actor rows can claim them, not so any caller
  can rewrite history.
- **No two-party rule on this endpoint.** Soft metadata changes
  don't carry a propose/accept handshake — there's nothing to gate.
  Per-write attribution for *content* changes lives on the
  proposal/accept rows already.
- **Per-version actor on history.** The history endpoint
  (`GET /contracts/{contract_id}/history`) surfaces
  `proposer_actor` / `acceptor_actor` / `single_operator_override`
  on each entry (provider v0.21.0+, #54) — useful for auditing who
  drove which past change.
