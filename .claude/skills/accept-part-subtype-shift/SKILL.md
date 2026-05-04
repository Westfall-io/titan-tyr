---
name: accept-part-subtype-shift
description: Accept an open part subtype-shift proposal — promote it from `proposal` to `accepted` and apply the new subtype to the part row. Use when the user wants to land a previously-proposed shift — e.g. "accept the shift on payments-service to container", "promote subtype proposal abc123". Lists open shift proposals, confirms the chosen one, and POSTs to /parts/{name}/subtype-proposals/{proposal_id}/accept. Enforces the proposer-doesn't-accept rule via the X-Actor header (with `?single_operator=true` as an explicit override for solo setups). Acceptance does NOT mutate the body or version — only the structural discriminator changes.
---

# accept-part-subtype-shift

You are promoting a previously-drafted part subtype shift to
`accepted`. Acceptance is the deliberate counterpart to
`/propose-part-subtype-shift`: the propose skill drafts and submits;
this skill lands.

This is the **only mutating step** in the part shift flow. Treat the
final POST as load-bearing: do not run it without an explicit user
confirmation on the exact proposal about to land, and **do not run
it under the same `X-Actor` as the proposer** (proposer-doesn't-accept
rule, with `?single_operator=true` as the documented override).

## Server location

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |
| `TITAN_TYR_ACTOR` | no       | Identity for the X-Actor header. **Strongly recommended** here — without it the two-party rule cannot be enforced and the API allows anyone to accept. |

If `TITAN_TYR_URL` is unset, **stop and tell the user**.

## Workflow

### 1. Confirm reachability and target part

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

Then verify the part exists:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{name}"
```

`404` → stop.

### 2. List open shift proposals

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{name}/subtype-proposals"
```

Render every proposal whose `status == "proposal"` (the listing
includes accepted ones too — those are read-only history). Show:

- `proposal_id` (truncated for display, full for the accept call)
- `current_subtype` → `new_subtype`
- `proposer_actor` (the X-Actor at propose time)
- `created_at`
- `rationale`
- `impact.body_realign_required`
- `impact.related_rows_potentially_affected` count

If there are no open proposals, **stop** — nothing to accept. Point
the user at `/propose-part-subtype-shift` if they wanted to draft one.

### 3. Confirm the target proposal

If multiple open proposals exist, ask which one. If only one, suggest
it as the default. Re-show the rationale and impact preview before
accepting — the impact may have changed since propose time as related
rows shifted independently.

If `proposer_actor == TITAN_TYR_ACTOR` and the user hasn't set
`single_operator`, **stop and explain the rule**: the same human
shouldn't both propose and accept a structural change. Options:

1. Have a different operator accept (set `TITAN_TYR_ACTOR` to a
   different value for this run).
2. Pass `?single_operator=true` if this is a one-person setup —
   document the choice in the user reply.

### 4. Final preview

```
About to accept part subtype shift on `<name>`:
  shift: <current> → <new>
  proposed by: <actor>
  rationale: "<rationale>"
  body realign needed after: <yes|no>
  related rows that will become invalid: <count>

After this, GET /parts/<name> will return subtype=<new>. The body is
untouched. Proceed?
```

Wait for an unambiguous yes. "Looks good" is yes; silence is not.

### 5. POST the accept

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  "$TITAN_TYR_URL/parts/{name}/subtype-proposals/{proposal_id}/accept"
```

If using single-operator override:

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  "$TITAN_TYR_URL/parts/{name}/subtype-proposals/{proposal_id}/accept?single_operator=true"
```

### 6. Report

On `200`:

```
Accepted. Part `<name>` is now subtype=<new> (was <old>).
Body and version are unchanged.
Proposer: <proposer_actor or "anonymous">. Acceptor: <accepted_by or "anonymous">.

Verify:
  curl -H 'Authorization: Bearer $TITAN_TYR_TOKEN' $TITAN_TYR_URL/parts/<name>

Follow-ups (if any):
  - body_realign_required: file a content proposal via the part PUT
    surface to re-stamp the body to <new>@<active-template-version>
  - related rows now invalid: each one needs its own shift via
    /propose-contract-subtype-shift
```

If the response carries `single_operator_override: true` (provider
v0.16.0+, #38), surface it loudly in the summary:

> ⚠ Accepted under single-operator override (`?single_operator=true`).
> The two-party rule was bypassed for this shift. The flag is
> recorded on the proposal row so the bypass is visible in the
> audit trail; mention it explicitly so operators reviewing later
> see it.

If `proposer_actor` or `accepted_by` is null, surface that — the
rule was unenforceable and that fact should be visible.

Then surface any related rows that the propose-time impact preview
flagged. They were informational at propose time and still are now —
the user opts in by accepting.

### 7. Audit downstream (optional)

If `body_realign_required` was true, the audit recipe from
`/accept-template-proposal` step 8 still applies: walk the related
parts/contracts and check stamp drift. The shift just made one row
explicitly drift; the broader audit catches everything else.

## Error handling

| Status | Meaning                                                                          | What to do                                                                  |
| ------ | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `404`  | Part name or `proposal_id` doesn't exist                                         | Re-list proposals; check the part name.                                     |
| `409`  | Proposal already accepted, or no-op (concurrent shift landed first)              | Re-list to see current state; the proposal is stale.                        |
| `422`  | `proposer_actor == acceptor_actor` without `single_operator=true`                | Surface the rule; have a different actor accept or set the override.        |

## Notes

- **Body is not mutated.** Only `parts.subtype`,
  `parts.subtype_shifted_from`, and `parts.subtype_shifted_at` change.
  The version row is untouched.
- **No undo.** Acceptance is reversible only by proposing the
  reverse shift (and accepting that). Treat acceptance as load-bearing.
- **History endpoint** picks up the shift event automatically:
  `GET /parts/<name>/history` returns one entry per body bump
  *and* one per accepted shift, distinguished by the `kind` field
  (`body_bump` or `subtype_shift`).
- **Acceptance re-validates.** A shift proposed against subtype X
  may no longer apply if the part has shifted independently in the
  meantime — the accept endpoint detects no-ops and 409s. Re-propose
  if the user still wants the change.
