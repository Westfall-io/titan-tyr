---
name: learn-contract
description: Look up everything titan-tyr knows about a registered contract by id — its body, endpoints with their current subtypes, open content proposals, open subtype-shift proposals, and the timeline of accepted changes. Use when an agent has a contract_id (e.g. from /find-part or /learn-part's touching-contracts listing) and needs the full picture before acting. Returns structured JSON. Read-only. Distinct from /propose-contract-change (which mutates) and /find-part / /learn-part (which discover by name, not id).
---

# learn-contract

You are answering an agent's "tell me about contract X" question by
pulling everything titan-tyr knows about it: subtype + connection_type
discriminator, body, endpoint parts (with their current subtypes), open
content proposals, open subtype-shift proposals, and the most recent
shift attribution if any.

This skill is **read-only and non-mutating**. It composes existing
titan-tyr GET endpoints into a single structured response so a calling
agent doesn't have to fetch and stitch four endpoints itself —
mirroring `/learn-part`'s role for parts.

The action surfaces (propose, accept) remain separate skills:
`/propose-contract-change`, `/propose-contract-subtype-shift`,
`/accept-contract-proposal` (which auto-branches between content +
shift acceptance).

## Server location

Same env vars as the other titan-tyr skills:

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |

If `TITAN_TYR_URL` is unset, **stop and tell the user**:

> `TITAN_TYR_URL` is not set. Set it to the titan-tyr base URL before running this skill, e.g.
> `export TITAN_TYR_URL=http://localhost:8000`.

Don't guess. Don't default to localhost silently.

## Inputs

| Input         | Required | Purpose                                                                                                       |
| ------------- | -------- | ------------------------------------------------------------------------------------------------------------- |
| `contract_id` | yes      | Full UUID of the contract. No partial / by-name lookup here — use `/find-part` + `/learn-part` to find an id. |

## Workflow

### 1. Confirm reachability

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → wrong token. Stop.
- Connection refused → wrong URL or server down. Stop.

### 2. Fetch the contract (existence probe + full body)

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/$contract_id"
```

`404` → return the not-found shape (step 6). `200` → continue.

### 3. Fetch open content proposals + open subtype-shift proposals (parallel)

These two GETs are independent of each other and of step 2 (the
contract row itself doesn't gate either listing). Issue them in
parallel:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/$contract_id/proposals"

curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/$contract_id/subtype-proposals"
```

Filter the **content-proposals** response to entries where
`version > active_version` under semver ordering — the listing
already excludes superseded RCs, but the response shape still
includes them in the `proposals` array. Surface every entry that
made the cut.

Filter the **shift-proposals** response client-side to
`status == "proposal"` — accepted shifts are historical and
surface on `/contracts/{id}/history` instead.

Pre-v0.16.0 servers may `404` on subtype-proposals (shipped in
v0.15.0) or omit the actor fields on content-proposal listings
(shipped in v0.16.0). Degrade gracefully — emit empty arrays /
null fields rather than failing the whole skill.

### 4. Compose the response

Merge into one structured payload. Don't re-fetch endpoint-part
detail (the contract response already carries `owner` /
`counterparty` names + their current subtypes via the listing
endpoint where available). If the per-part detail is needed, the
caller can follow up with `/learn-part`.

### 5. Return the "found" response

```json
{
  "status": "found",
  "contract": {
    "contract_id": "...",
    "owner": "payments-service",
    "counterparty": "orders-service",
    "subtype": "interaction",
    "connection_type": null,
    "version": "1.2.0",
    "markdown": "...",
    "subtype_shifted_from": null,
    "subtype_shifted_at": null,
    "created_by_actor": "alice",
    "updated_at": "..."
  },
  "open_content_proposals": [
    {
      "version": "1.3.0-rc1",
      "created_at": "...",
      "proposer_actor": "alice",
      "proposer_attribution": "alice",
      "next_step": "to accept: /accept-contract-proposal target=<contract_id>"
    }
  ],
  "open_subtype_shifts": [
    {
      "proposal_id_short": "7d3e1c2b",
      "proposal_id": "7d3e1c2b-...",
      "current_subtype": "interaction",
      "current_connection_type": null,
      "new_subtype": "binding",
      "new_connection_type": null,
      "rationale": "...",
      "proposer_actor": "alice",
      "proposer_attribution": "alice",
      "created_at": "...",
      "impact": {
        "body_realign_required": true,
        "source_target_validation": "pass",
        "related_rows_potentially_affected": []
      },
      "next_step": "to accept: /accept-contract-proposal target=<contract_id> (auto-branches to shift)"
    }
  ]
}
```

Field notes:

- `contract.subtype` is the discriminator (one of `interaction`,
  `binding`, `connection`). For `connection`, `connection_type` is
  the per-label sub-discriminator (one of `builds-from`,
  `instantiates`, `runs`, `member-of`, `depends-on`, `submodule`).
  For other subtypes, `connection_type` is `null`.
- `contract.subtype_shifted_from` / `subtype_shifted_at` (nullable,
  provider v0.15.0+) surface the most recent accepted subtype
  shift. `null` if the contract has never been shifted. Calling
  agents should surface this so users know the discriminator was
  corrected post-registration.
- `contract.created_by_actor` (nullable, provider v0.16.0+) is the
  X-Actor recorded at `POST /contracts` time. Pre-v0.16.0
  contracts have `null`.
- `open_content_proposals` is the list of pending body proposals
  newer than the active version. Always present; empty array when
  none. Each entry's `proposer_attribution` is the human-readable
  label: the `proposer_actor` value when set, else
  `"anonymous (two-party rule unenforceable)"`.
- `open_subtype_shifts` is the list of pending shift proposals
  (filtered to `status == "proposal"`). Always present; empty
  array when none. Same `proposer_attribution` convention applies.
- `next_step` for both arrays points at
  `/accept-contract-proposal`. That skill auto-branches between
  content and shift acceptance based on which kind of open
  proposal it finds.

Calling agents should branch on whether either array is non-empty
before acting on `contract.subtype` / `contract.connection_type` /
`contract.markdown` — a pending shift means the discriminator is
in flight; a pending content proposal means the body is about to
move.

### 6. Return the "not found" response (404 from step 2)

```json
{
  "status": "not_found",
  "contract_id": "<provided>",
  "hint": "No contract with that id. To find a contract by name, call /find-part on either endpoint and check its contracts listing for contract_ids."
}
```

## Caller-side composition

`/learn-contract` is meant to be called from another agent's
context. Common composition:

1. Agent has "what's the deal between A and B?"
2. Calls `/find-part query="A"` → resolves the slug.
3. Calls `/learn-part target=<slug>` → reads the touching-contracts
   listing → extracts the relevant `contract_id`.
4. Calls `/learn-contract contract_id=<id>` → reads the body, sees
   any pending shifts or content proposals, and acts.

The skill itself does not print prose summaries or ask the user to
disambiguate — that's the calling agent's job. The structured JSON
return value is the contract.

## Error handling

| Status | Meaning                                  | What to do                                                        |
| ------ | ---------------------------------------- | ----------------------------------------------------------------- |
| `401`  | Bad bearer token                         | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                       |
| `404`  | Unknown contract_id                      | Return the not-found shape; don't propagate the 404 to the caller.|
| `422`  | `contract_id` not a UUID                 | Stop. Surface `detail` so the caller can fix the input.           |
| `5xx`  | Server problem                           | Stop. Print response body verbatim.                               |

## Notes

- This skill is read-only. It never POSTs / PUTs / DELETEs anything.
- For the inverse direction ("I have a part name, give me everything"),
  call `/learn-part`. For colloquial-label resolution, call
  `/find-part` first.
- The response intentionally does **not** fetch full part-detail
  bodies for the contract's endpoints — the contract surface is
  what the caller asked about. If the caller needs endpoint detail,
  follow up with `/learn-part target=<owner>` or
  `/learn-part target=<counterparty>`.
- Pre-v0.16.0 servers may not surface `created_by_actor` on the
  contract response or actor fields on content-proposal listings.
  Degrade gracefully — render missing fields as `null`.
- `next_step` strings name skills, not raw curl commands, because
  the action surfaces enforce additional invariants (two-party
  rule, source/target re-validation on accept) that the calling
  agent should route through the skill rather than re-implement.
