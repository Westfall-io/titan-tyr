---
name: propose-part-subtype-shift
description: Propose a structural subtype change for a registered part — e.g. "this was registered as software but is actually a container", "shift the payments-image part to subtype=image". Use when a part's subtype was set wrong on first registration and needs correction without losing the canonical name, version history, or existing contracts. Pre-validates the impact (which contracts would break under the new subtype, whether the body needs realignment), confirms with the user, and POSTs to /parts/{name}/subtype-proposals. Does NOT accept the proposal — acceptance is the deliberate counterpart via /accept-part-subtype-shift.
---

# propose-part-subtype-shift

You are drafting a proposed **subtype shift** for a registered part.
Subtype shifts are a separate flow from content (body) proposals: the
body is not mutated, the version is not bumped, only the row's
structural discriminator (`parts.subtype`) changes on accept.

This skill **creates the proposal** and never accepts it. Acceptance
goes through `/accept-part-subtype-shift` and **must be performed by
a different X-Actor** (proposer-doesn't-accept rule, with
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

`200` → continue. `401` → wrong token, stop. Connection refused →
wrong URL or server down, stop.

### 2. Resolve the part

Take the part name from the user. Pre-flight that it exists:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{name}" \
  | python3 -c "import json, sys; d=json.load(sys.stdin); print(d['name'], d['subtype'], d['version'])"
```

`404` → stop, the part isn't registered. Use `/find-part` first.

Show the user the current `subtype` so they can confirm the shift
target makes sense relative to it.

### 3. Pick the new subtype

Ask which subtype the part should shift to. Valid Part subtypes
today (provider v0.14.0+):

| Subtype     | When this is the right shift target                                                       |
| ----------- | ----------------------------------------------------------------------------------------- |
| `software`  | Codebase / deployable boundary. Shift here from container/image/pod/compose if mis-classified as a runtime when it's actually a repo. |
| `container` | Single Docker / Compose runtime instance. Shift here from software if it's actually the running thing, not the source. |
| `image`     | Built artifact (tagged image, Helm chart, packaged binary). Shift here from software/container if it represents what's *built*, not the source or the running instance. |
| `pod`       | K8s scheduled unit. Shift here from container if the runtime is K8s-orchestrated, not Docker / Compose. |
| `compose`   | Docker Compose stack — metadata about a `compose.yaml`. Shift here from software/container if it represents the *stack*, not a single service. |

**No-op shifts (`new_subtype == current`) are rejected with 409.**
If the user proposes a no-op, tell them the part is already that
subtype.

### 4. Get the rationale

Ask the user *why* the shift is needed. The rationale is a required
field (1-2000 chars) and lands in the proposal record. A good
rationale describes the misclassification cause — "registered as
software but actually represents the prod deployment instance, see
DESIGN.md" — not just "wrong subtype".

### 5. POST the proposal — surface the impact preview

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  --data @.scratch/part-shift-proposal.json \
  "$TITAN_TYR_URL/parts/{name}/subtype-proposals"
```

The response carries an `impact` block:

```json
{
  "proposal_id": "...",
  "current_subtype": "software",
  "new_subtype": "container",
  "impact": {
    "body_realign_required": false,
    "source_target_validation": "n/a",
    "related_rows_potentially_affected": [
      {
        "contract_id": "...",
        "owner": "<this-part>",
        "counterparty": "<other-part>",
        "subtype": "binding",
        "reason": "binding owner must be in ['container', 'pod']; new owner subtype would be 'image'"
      }
    ]
  }
}
```

Show the user every entry in `related_rows_potentially_affected`.
Each one is a contract that would become invalid post-shift —
acceptance does **not** auto-cascade. The user must file separate
shift proposals on each affected row before acceptance, or accept
this one knowing the related rows will become structurally broken.

If `body_realign_required: true`, the body's first-line stamp is
on the wrong template kind. Flag it: "after acceptance, file a
content proposal that re-stamps the body to `<new-subtype>@<active-template-version>`."

### 6. Stop here

Do **not** call the accept endpoint. Tell the user the
`proposal_id` and that acceptance goes through
`/accept-part-subtype-shift` (must be a different `X-Actor`, or
pass `?single_operator=true` for solo setups).

## Error handling

| Status | Meaning                                                                                | What to do                                                  |
| ------ | -------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `404`  | Part name not registered                                                               | Stop; point user at `/register-part`.                       |
| `409`  | No-op shift (`new_subtype == current`)                                                 | Tell user the part is already that subtype.                 |
| `422`  | Unknown `new_subtype` value, missing `rationale`, or `rationale` length out of bounds | Re-prompt; show the allowed subtype list.                   |

## Notes

- **Body is not touched.** Subtype shifts and content edits are
  orthogonal axes. If the new subtype's template differs structurally
  from the old one, follow up with `/propose-contract-change` (or
  `/propose-template-change` chain — though parts use the version
  endpoints, not the contract proposal endpoints) to realign the
  body. The shift acceptance flags this via `body_realign_required`.
- **Two-party rule is structural.** The `X-Actor` header is the
  signal until real auth lands. Solo setups override the rule on
  accept via `?single_operator=true` — this skill records the
  proposer; the accept skill checks the acceptor.
- **No automatic cascade.** Each impacted contract gets its own
  explicit shift proposal. The impact preview surfaces them so the
  user can plan, but acceptance does not block on related-row state.
