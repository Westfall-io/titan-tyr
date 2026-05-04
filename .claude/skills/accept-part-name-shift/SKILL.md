---
name: accept-part-name-shift
description: Accept an open part name-shift proposal — promote it from `proposal` to `accepted` and rename the part row. Use when the user wants to land a previously-proposed rename — e.g. "accept the rename of payments-svc to payments-service", "promote name proposal abc123". Lists open name proposals, confirms the chosen one, and POSTs to /parts/{name}/name-proposals/{proposal_id}/accept. Enforces the proposer-doesn't-accept rule via the X-Actor header (with `?single_operator=true` as an explicit override). Acceptance does NOT mutate the body, version, contracts, or proposal history — only `parts.name` changes (plus rename bookkeeping cols).
---

# accept-part-name-shift

You are promoting a previously-drafted part name shift to
`accepted`. Acceptance is the deliberate counterpart to
`/propose-part-name-shift`: the propose skill drafts and submits;
this skill lands.

This is the **only mutating step** in the part name-shift flow. Treat
the final POST as load-bearing: do not run it without an explicit
user confirmation on the exact proposal about to land, and **do not
run it under the same `X-Actor` as the proposer**
(proposer-doesn't-accept rule, with `?single_operator=true` as the
documented override).

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

Then verify the part exists at its current slug:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{name}"
```

`404` → stop. The slug may have already shifted; re-confirm with
the user which name to use.

### 2. List open name proposals

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{name}/name-proposals"
```

Render every proposal whose `status == "proposal"` (the listing
includes accepted ones too — those are read-only history). Show:

- `proposal_id` (truncated for display, full for the accept call)
- `current_name_at_propose` → `new_name`
- `proposer_actor` (the X-Actor at propose time)
- `created_at`
- `rationale`

If there are no open proposals, **stop** — nothing to accept. Point
the user at `/propose-part-name-shift` if they wanted to draft one.

### 3. Confirm the target proposal

If multiple open proposals exist, ask which one. If only one, suggest
it as the default. Re-show the rationale before accepting.

If `proposer_actor == TITAN_TYR_ACTOR` and the user hasn't set
`single_operator`, **stop and explain the rule**: the same human
shouldn't both propose and accept a structural change. Options:

1. Have a different operator accept (set `TITAN_TYR_ACTOR` to a
   different value for this run).
2. Pass `?single_operator=true` if this is a one-person setup —
   document the choice in the user reply.

### 4. Final preview

```
About to accept part name shift on `<current>`:
  rename: <current> → <new>
  proposed by: <actor>
  rationale: "<rationale>"

After this, GET /parts/<current> will 404 and GET /parts/<new> will
serve the part. Body, version, and contract endpoints are unchanged
— contract responses will surface the new name automatically on
the next GET via the join. Proceed?
```

Wait for an unambiguous yes. "Looks good" is yes; silence is not.

### 5. POST the accept

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  "$TITAN_TYR_URL/parts/{name}/name-proposals/{proposal_id}/accept"
```

If using single-operator override:

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  "$TITAN_TYR_URL/parts/{name}/name-proposals/{proposal_id}/accept?single_operator=true"
```

### 6. Report

On `200`:

```
Accepted. Part renamed: <old> → <new>.
Body and version are unchanged. Contracts touching this part will
surface the new name automatically on the next GET.
Proposer: <proposer_actor or "anonymous">. Acceptor: <accepted_by or "anonymous">.

Verify:
  curl -H 'Authorization: Bearer $TITAN_TYR_TOKEN' $TITAN_TYR_URL/parts/<new>

Follow-ups:
  - The old slug now 404s. Any deployed UI build, script, or skill
    holding the old name needs to refresh / be updated.
  - Audit downstream callers (CLAUDE.md, scripts) for hard-coded
    references to `<old>`.
```

If the response carries `single_operator_override: true`, surface it
loudly in the summary:

> ⚠ Accepted under single-operator override (`?single_operator=true`).
> The two-party rule was bypassed for this rename. The flag is
> recorded on the proposal row so the bypass is visible in the
> audit trail.

If `proposer_actor` or `accepted_by` is null, surface that — the
rule was unenforceable and that fact should be visible.

## Error handling

| Status | Meaning                                                                          | What to do                                                                  |
| ------ | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `404`  | Part name or `proposal_id` doesn't exist (or the part already shifted)           | Re-list proposals; check the part name.                                     |
| `409`  | Proposal already accepted, no-op (concurrent shift landed first), or the proposed slug is now taken by another part | Re-list to see current state; the proposal may be stale or need re-filing. |
| `422`  | `proposer_actor == acceptor_actor` without `single_operator=true`                | Surface the rule; have a different actor accept or set the override.        |

## Notes

- **Body, version, and contracts are not mutated.** Only
  `parts.name`, `parts.name_shifted_from`, and `parts.name_shifted_at`
  change. Contracts pick up the new name on next GET via the FK join.
- **No undo.** Acceptance is reversible only by proposing the
  reverse rename (and accepting that). Treat acceptance as
  load-bearing.
- **History endpoint** picks up the rename event automatically:
  `GET /parts/<new>/history` returns one entry per body bump *and*
  one per accepted name shift, distinguished by the `kind` field
  (`body_bump`, `subtype_shift`, or `name_shift`).
- **Acceptance re-validates.** A rename proposed against slug X may
  no longer apply if another part has taken X in the meantime — the
  accept endpoint detects collisions and 409s. Re-propose with a
  different slug if the user still wants the change.
- **Old slug is gone.** There is no server-side alias / redirect.
  Consumers holding the old slug will 404 against
  `GET /parts/{old}`. If you need a grace period, coordinate the
  client cutover before accepting.
