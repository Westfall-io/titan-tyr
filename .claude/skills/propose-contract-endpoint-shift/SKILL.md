---
name: propose-contract-endpoint-shift
description: Propose a structural endpoint change for an existing contract — e.g. "this binding's owner should be a different container", "swap this connection's counterparty to the new prod service". Use when one or both endpoint parts of a contract were set wrong on registration and need correction without losing the contract id, version history, or proposal trail. Pre-validates the new endpoints against the contract's source/target rule and the widened uniqueness key from #42, then POSTs to /contracts/{contract_id}/endpoint-proposals. Does NOT accept the proposal — acceptance is the deliberate counterpart via /accept-contract-endpoint-shift.
---

# propose-contract-endpoint-shift

You are drafting a proposed **endpoint shift** for an existing
contract. Endpoint shifts are a separate flow from content (body)
proposals: the body is not mutated, the version is not bumped, only
one or both of `owner_part_id` / `counterparty_part_id` change on
accept. The contract keeps its id, version row(s), and proposal
history — the relationship is *re-pointed*, not re-created.

This skill **creates the proposal** and never accepts it. Acceptance
goes through `/accept-contract-endpoint-shift` and **must be performed
by a different X-Actor** (proposer-doesn't-accept rule, with
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
    "$TITAN_TYR_URL/parts/{name}/contracts"
  ```

  Show the user each row with its current endpoints + subtype, and
  ask which contract.

Then GET the resolved contract to confirm:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}"
```

Surface its current `(owner, counterparty, subtype, connection_type)`
to the user before they pick the new endpoints.

### 3. Pick the new endpoint(s)

Ask which side(s) need to shift. **At least one of `new_owner` /
`new_counterparty` must be set, and the resulting (owner,
counterparty) pair must differ from the current pair.** A one-sided
shift only changes the side that's specified; the other side
remains as recorded.

Pre-flight that each new endpoint exists:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{new_endpoint_name}" \
  | python3 -c "import json, sys; d=json.load(sys.stdin); print(d['name'], d['subtype'])"
```

`404` → stop, the part isn't registered. Use `/find-part` first.

### 4. Validate the source/target rule client-side (optional preview)

The server hard-blocks at propose time if the new endpoint subtypes
violate the contract's per-subtype rule:

| Contract subtype | Owner subtype rule         | Counterparty subtype rule       |
| ---------------- | -------------------------- | ------------------------------- |
| `interaction`    | any                        | any                             |
| `binding`        | container, pod, compose    | software                        |
| `connection`     | per `connection_type`      | per `connection_type`           |

If the user picks an endpoint that obviously violates the rule, warn
them before POSTing — the API will 422 with the same reason. Either
shift the endpoint *part's* subtype first (via
`/propose-part-subtype-shift`), or shift the *contract's* subtype
first (via `/propose-contract-subtype-shift`), or pick a different
endpoint.

### 5. Validate uniqueness client-side (optional preview)

After the shift, the resulting `(owner_part_id, counterparty_part_id,
subtype, connection_type)` tuple must be unique (per #42's widened
uniqueness key). If another contract with the same shape between the
new endpoints already exists, the API will 409. To pre-check, list
contracts touching the new endpoint(s) and look for a matching subtype:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{new_owner}/contracts"
```

### 6. Get the rationale

Ask the user *why* the shift is needed. The rationale is required
(1-2000 chars) and lands in the proposal record. A good rationale
describes the cause — "owner part was registered against the legacy
service ahead of the cutover; new prod service is now the
authoritative source" — not just "wrong endpoint".

### 7. POST the proposal

Build the JSON body. Either or both of `new_owner` / `new_counterparty`
may be set; omit the side that's not changing.

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  --data @.scratch/contract-endpoint-shift.json \
  "$TITAN_TYR_URL/contracts/{contract_id}/endpoint-proposals"
```

Surface the response — it carries `proposal_id`, the snapshot of
current endpoints, and the proposed new endpoint name(s).

### 8. Stop here

Do **not** call the accept endpoint. Tell the user the
`proposal_id` and that acceptance goes through
`/accept-contract-endpoint-shift` (must be a different `X-Actor`, or
pass `?single_operator=true` for solo setups).

## Error handling

| Status | Meaning                                                                                | What to do                                                  |
| ------ | -------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `404`  | `contract_id` doesn't exist, or one of the new endpoint slugs isn't registered         | Re-check the id; verify endpoints exist via `/find-part`.   |
| `409`  | Resulting endpoint pair would collide with an existing contract of the same subtype     | Pick a different endpoint, or shift the colliding contract first. |
| `422`  | Neither side set, no-op (resolves to current pair), self-loop (owner == counterparty after shift), source/target rule violation, or invalid slug | Re-prompt; show the rule above and the current endpoints. |

## Notes

- **Body is not touched.** Endpoint shifts and content edits are
  orthogonal axes. Version history and template stamps survive the
  shift unchanged.
- **One-sided shifts are allowed.** Set only the side that's
  changing. The other side remains as recorded; bookkeeping cols
  (`endpoint_shifted_from_owner` / `endpoint_shifted_from_counterparty`)
  capture the side(s) that actually moved.
- **Two-party rule is structural.** The `X-Actor` header is the
  signal until real auth lands. Solo setups override the rule on
  accept via `?single_operator=true` — this skill records the
  proposer; the accept skill checks the acceptor.
- **Acceptance re-validates.** Source/target rule and uniqueness
  are re-checked at accept time; a proposal that passed at propose
  time may 422/409 on accept if endpoint subtypes shifted or a new
  colliding contract was created in the meantime.
