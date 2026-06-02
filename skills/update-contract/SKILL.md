---
name: update-contract
description: Update soft metadata on an existing contract (project tag). Does NOT change body — use /propose-contract-change. Does NOT change ownership — use /reassign-contract-owner.
---

# update-contract

You are PUT-ing soft metadata on an existing contract. This is the
parallel to `/update-part` for contracts, scoped tightly: the only
field this PUT touches today is `project` (optional tag).

Ownership (`owner_actor`) is **not** touched by this PUT. To reassign
ownership, use `/reassign-contract-owner` (wraps `PUT
/contracts/{contract_id}/owner` — single write, no two-party rule,
overwrite allowed). The first-write-wins backfill this PUT used to
perform was removed in #119.

Use cases:
- **Tag a contract to a project.** The `project` field on
  `POST /contracts` was added in v0.18.0 (#44); contracts registered
  before that are stuck at `project: null` until updated through
  this surface.
- **Re-project a contract.** Move it between projects, or clear the
  tag back to unprojected.

This skill **does not** propose body changes, shift subtypes, shift
endpoints, rename anything, or change ownership. Each has its own
dedicated flow.

## Server location

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | yes      | Bearer per-caller token (issue via `/issue-auth-token`). |

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

Surface its current `project` so the user can see the starting state.

### 3. Decide what's changing

PATCH semantics on `project`:

| Field     | Omitted from body         | `"project": "<slug>"`                        | `"project": null`                |
| --------- | ------------------------- | -------------------------------------------- | -------------------------------- |
| `project` | Existing tag unchanged.   | Reassigns to that project (422 if unknown).  | Clears tag (move to unprojected). |

If the user wants no project change — **stop**. There's nothing to do;
this PUT would be a no-op. If they want to reassign ownership instead,
route them to `/reassign-contract-owner`.

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
  --data '{"project": "<slug>"}' \
  "$TITAN_TYR_URL/contracts/{contract_id}"
```

Or to clear the project tag:

```sh
  --data '{"project": null}' \
```

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
  version: <unchanged>

Verify (optional, the response above is authoritative):
  curl -H 'Authorization: Bearer $TITAN_TYR_TOKEN' $TITAN_TYR_URL/contracts/<contract_id>
```

## Error handling

| Status | Meaning                                                                          | What to do                                                                                |
| ------ | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `404`  | Contract id doesn't exist                                                        | Re-resolve via `?owner=&counterparty=` or `/parts/{name}/contracts`.                      |
| `422`  | `project` slug is malformed (uppercase, dots, etc.) or references an unknown project | Re-prompt; verify with `/list-projects` or `/register-project`.                       |

## Notes

- **Body / version / subtype / connection_type / endpoints / ownership
  don't belong here.** Use the dedicated flows:
  `/propose-contract-change` (body), `/propose-contract-subtype-shift`
  (subtype + connection_type), `/propose-contract-endpoint-shift`
  (endpoints), `/reassign-contract-owner` (ownership), plus the
  matching `/accept-*` skills for the propose/accept flows. This PUT
  is exclusively for the `project` tag.
- **No two-party rule on this endpoint.** Soft metadata changes
  don't carry a propose/accept handshake — there's nothing to gate.
  Per-write attribution for *content* changes lives on the
  proposal/accept rows already.
- **Per-version actor on history.** The history endpoint
  (`GET /contracts/{contract_id}/history`) surfaces
  `proposer_actor` / `acceptor_actor` / `single_operator_override`
  on each entry — useful for auditing who drove which past change.
