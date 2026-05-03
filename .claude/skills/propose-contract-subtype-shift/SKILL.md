---
name: propose-contract-subtype-shift
description: Propose a structural subtype change for an existing contract — e.g. "this interaction should be a binding", "shift this connection to use member-of instead of depends-on". Use when a contract's subtype (or connection_type label) was set wrong on registration and needs correction without losing the version history. Pre-validates the new subtype's source/target rule against the current endpoint parts, surfaces whether the body needs realignment, and POSTs to /contracts/{contract_id}/subtype-proposals. Does NOT accept the proposal — acceptance is the deliberate counterpart via /accept-contract-proposal (which now branches on whether an open shift is found).
---

# propose-contract-subtype-shift

You are drafting a proposed **subtype shift** for an existing
contract. Subtype shifts are a separate flow from content (body)
proposals: the body is not mutated, the version is not bumped, only
the row's structural discriminators (`subtype` and, for connection
contracts, `connection_type`) change on accept.

This skill **creates the proposal** and never accepts it. Acceptance
goes through `/accept-contract-proposal` (which detects open shift
proposals automatically) and **must be performed by a different
X-Actor** than the proposer (proposer-doesn't-accept rule, with
`?single_operator=true` as an explicit override for solo setups).

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

  If both directions might exist, ask which the user means. Surface
  the current `subtype` and (if connection) `connection_type`.

- **They gave one part name.** List touching contracts:

  ```sh
  curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
    "$TITAN_TYR_URL/parts/{name}/contracts?limit=100"
  ```

  Render with subtype + connection_type and ask which.

Pre-flight that the chosen contract exists:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}" \
  | python3 -c "import json, sys; d=json.load(sys.stdin); print(d['owner'], '->', d['counterparty'], d['subtype'], d.get('connection_type'))"
```

### 3. Pick the new subtype (and connection_type if applicable)

Ask which subtype the contract should shift to. Valid contract
subtypes: `interaction`, `binding`, `connection`. If `connection`,
also prompt for `new_connection_type` (one of: `builds-from`,
`instantiates`, `runs`, `member-of`, `depends-on`, `submodule`).

The provider pre-validates the new subtype's source/target rule
against the current endpoint parts. Walk through the rule tables
with the user **before** POSTing so they aren't surprised by a 422:

| Subtype       | Source (owner) rule         | Target (counterparty) rule |
| ------------- | --------------------------- | -------------------------- |
| `interaction` | any                         | any                        |
| `binding`     | `container` or `pod`        | `software`                 |
| `connection`  | per-label (see below)       | per-label                  |

| `connection_type` | Owner part subtype  | Counterparty part subtype |
| ----------------- | ------------------- | ------------------------- |
| `builds-from`     | `software`          | `image`                   |
| `instantiates`    | `image`             | `container` or `pod`      |
| `runs`            | `container` or `pod`| `software`                |
| `member-of`       | `container`         | `compose`                 |
| `depends-on`      | `container`         | `container`               |
| `submodule`       | `software`          | `software`                |

If the proposed shift would violate the rule, the propose endpoint
**hard-blocks with 422** (unlike part shifts, which only soft-warn
on related rows). The user must shift the endpoint parts first
(via `/propose-part-subtype-shift`), or pick a different new
subtype, before retrying.

**No-op shifts (same subtype + same connection_type) are rejected
with 409.** A connection-type-only change (subtype stays
`connection`, label changes) is **not** a no-op and is allowed.

### 4. Get the rationale

Required field, 1-2000 chars. A good rationale describes the
misclassification cause: "owner is actually a container, this is
environment-specific" or "no runtime data flows here, this is
purely a startup-ordering dependency".

### 5. POST the proposal

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  --data @.scratch/contract-shift-proposal.json \
  "$TITAN_TYR_URL/contracts/{contract_id}/subtype-proposals"
```

The response carries an `impact` block:

```json
{
  "proposal_id": "...",
  "current_subtype": "interaction",
  "current_connection_type": null,
  "new_subtype": "binding",
  "new_connection_type": null,
  "impact": {
    "body_realign_required": true,
    "source_target_validation": "pass",
    "related_rows_potentially_affected": []
  },
  "status": "proposal"
}
```

If `body_realign_required: true`, the body's first-line stamp is
on the wrong template kind. Flag it: "after acceptance, file a
content proposal via `/propose-contract-change` that re-stamps the
body to `<new-subtype>@<active-template-version>`."

### 6. Stop here

Do **not** call the accept endpoint. Tell the user the
`proposal_id` and that acceptance goes through
`/accept-contract-proposal` (which now branches on whether the open
proposal is a content proposal or a subtype shift — must be a
different `X-Actor`, or pass `?single_operator=true` for solo setups).

## Error handling

| Status | Meaning                                                                                       | What to do                                                  |
| ------ | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `404`  | Contract not found                                                                            | Stop; verify the `contract_id`.                             |
| `409`  | No-op shift (subtype + connection_type both match current)                                    | Tell user the contract is already at that shape.            |
| `422`  | `new_connection_type` missing iff `new_subtype=connection` (or set otherwise), or new subtype's source/target rule violated by current endpoint subtypes, or rationale missing/out of bounds | Surface `detail`; user shifts endpoint parts first or picks different subtype. |

## Notes

- **Body is not touched.** Subtype shifts and content edits are
  orthogonal. Re-stamp via `/propose-contract-change` after the
  shift lands if `body_realign_required` was true.
- **Source/target hard-block.** Unlike part shifts (which surface
  related-row impact as informational), contract shifts hard-block
  if the new subtype's rule fails against current endpoints. The
  contract's own structural validity is the gate.
- **Connection-type-only shifts are allowed.** Same subtype
  (`connection`), different label. The provider re-validates the
  new label's per-label From/To rule.
- **Two-party rule.** Same as part shifts. The `X-Actor` header
  identifies proposer and acceptor; same actor is rejected unless
  `?single_operator=true` is set on accept.
