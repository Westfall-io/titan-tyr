---
name: propose-part-name-shift
description: Propose a structural rename of a registered part — e.g. "rename payments-svc to payments-service", "shift the slug `legacy-cart` to `cart`". Use when a part's slug needs correction without losing its id, version history, contracts, or proposal trail. Part `name` is the primary handle for callers, so the shift is structural rather than a body edit. Pre-validates that the new slug is free, confirms with the user, and POSTs to /parts/{name}/name-proposals. Does NOT accept the proposal — acceptance is the deliberate counterpart via /accept-part-name-shift.
---

# propose-part-name-shift

You are drafting a proposed **name shift** for a registered part.
Name shifts are a separate flow from content (body) proposals: the
body is not mutated, the version is not bumped, only the row's
primary handle (`parts.name`) changes on accept. Contracts hold
`owner_part_id` / `counterparty_part_id` by id (not by name), so the
rename does **not** cascade — existing contract rows surface the new
name on the next GET via the join automatically.

This skill **creates the proposal** and never accepts it. Acceptance
goes through `/accept-part-name-shift` and **must be performed by a
different X-Actor** (proposer-doesn't-accept rule, with
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

Take the current name from the user. Pre-flight that it exists:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{name}" \
  | python3 -c "import json, sys; d=json.load(sys.stdin); print(d['name'], d['subtype'], d['version'])"
```

`404` → stop, the part isn't registered. Use `/find-part` first.

### 3. Pick the new slug

Ask which slug the part should shift to. Slug rules (same pattern as
new-part registration):

- `^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$`
- 1-64 chars, lowercase, digits, single hyphens; no leading or
  trailing hyphen; no dots, underscores, slashes, or uppercase.

Pre-flight that the new slug is free:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{new_name}" -o /dev/null
```

`404` → free, proceed. `200` → already taken; the API will 409 at
propose time. Suggest an alternative.

**No-op shifts (`new_name == current`) are rejected with 409.** If the
user proposes a no-op, tell them the part is already at that slug.

### 4. Get the rationale

Ask the user *why* the rename is needed. The rationale is a required
field (1-2000 chars) and lands in the proposal record. A good
rationale describes the misnaming cause — "registered as svc-2 during
a migration; team standard is to drop the suffix once the legacy
service retires" — not just "wrong name".

### 5. POST the proposal

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  --data @.scratch/part-name-shift.json \
  "$TITAN_TYR_URL/parts/{name}/name-proposals"
```

The response carries the proposal id and the snapshot of current /
new names; surface them so the user sees what was filed.

### 6. Flag the consumer-side impact

A rename is structurally simple on the server (single UPDATE on
`parts.name`; contracts surface the new name automatically), but
**any caller holding the old slug as a string will 404 against
`GET /parts/{old}` after acceptance**. Warn the user:

- Deployed UIs (titan-mimiron) will need to refresh — render-only
  consumers don't track shift events on their own.
- Any scripts, cron jobs, or hard-coded references in CLAUDE.md
  files / skills will need an update before they're next run.
- The propose step itself is harmless; the consumer-visible cutover
  happens at accept.

### 7. Stop here

Do **not** call the accept endpoint. Tell the user the
`proposal_id` and that acceptance goes through
`/accept-part-name-shift` (must be a different `X-Actor`, or pass
`?single_operator=true` for solo setups).

## Error handling

| Status | Meaning                                                                                | What to do                                                  |
| ------ | -------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `404`  | Part name not registered                                                               | Stop; point user at `/register-part`.                       |
| `409`  | No-op (`new_name == current`), or the new slug is already taken by another part        | Pick a different slug; re-list with `/find-part`.           |
| `422`  | `new_name` slug invalid, missing `rationale`, or `rationale` length out of bounds      | Re-prompt; show the slug rules above.                       |

## Notes

- **Body is not touched.** Name shifts and content edits are
  orthogonal axes. Version history, body content, and template
  stamps survive the rename unchanged.
- **No FK cascade needed.** Contracts hold endpoints by id; the
  rename surfaces on the next contract GET via the join. There is
  no data-layer fallout from a rename.
- **Two-party rule is structural.** The `X-Actor` header is the
  signal until real auth lands. Solo setups override the rule on
  accept via `?single_operator=true` — this skill records the
  proposer; the accept skill checks the acceptor.
- **No automatic alias / redirect.** The old slug 404s after
  acceptance. If you need a grace period for consumers, file the
  rename behind a feature-flagged client cutover — the server has
  no concept of name aliasing.
