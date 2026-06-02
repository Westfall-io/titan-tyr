---
name: reassign-part-owner
description: Reassign ownership of a registered part to a new actor. Wraps PUT /parts/{name}/owner — single write, no two-party rule, overwrite allowed (#119).
---

# reassign-part-owner

You are reassigning the `owner_actor` of a part already registered
with titan-tyr. The endpoint is `PUT /parts/{name}/owner`. Single
write: no two-party handshake, no propose/accept dance. Overwrite is
allowed — there is no first-write-wins semantic (#119 superseded the
legacy backfill behavior).

The reassigning actor (`X-Actor` derived from your token) is
captured in the response as `reassigned_by_actor` for the audit
trail. The previous owner is captured as `previous_owner_actor`. Both
are surfaced to the caller; whether they're persisted as a history
entry is a follow-up.

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

### 2. Resolve the part + read its current owner

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/parts/{name}"
```

Surface the current `owner_actor` so the user can confirm the
starting state. `404` → part not registered; stop and route to
`/find-part`.

### 3. Get the new owner + rationale

Ask the user:
- **New owner slug** (1–64 chars, valid slug shape — same rule as
  part names and actor slugs).
- **Rationale** (1–2000 chars). Required field. Captures the *why*
  for the audit trail — "tyr-side work shifting to the tyr actor,"
  "handoff to incoming maintainer @x," "correcting misattribution
  from earlier handoff token," etc.

### 4. POST the reassignment

```sh
curl -fsS -X PUT \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"new_owner_actor": "<slug>", "rationale": "<text>"}' \
  "$TITAN_TYR_URL/parts/{name}/owner"
```

`200` → success; response carries `previous_owner_actor`,
`new_owner_actor`, `reassigned_by_actor`, `reassigned_at`,
`rationale`. `404` → part not found. `422` → missing/invalid
rationale or `new_owner_actor`.

### 5. Report

```
Reassigned ownership of part <name>:
  previous owner_actor: <previous>
  new owner_actor:      <new>
  reassigned by:        <your X-Actor>
  rationale:            <echo>
  at:                   <iso8601>

(Body / version unchanged. Reassignment does not bump the part's
semver — it's a metadata mutation.)
```

## Notes

- **No two-party rule.** Reassignment is a single-actor write. The
  reassigning actor's identity (derived from your token) is captured
  alongside the new owner so the audit trail records both sides of the
  handoff. If a future security event makes a propose/accept handshake
  necessary, that's a separate ticket.
- **Overwrite is allowed.** This is the post-#119 behavior. The old
  first-write-wins semantic (which only let `PUT /parts/{name}` claim
  a NULL `owner_actor`) is gone. You can reassign ownership any
  number of times.
- **Body version is not bumped.** Reassignment is a metadata
  mutation, parallel to subtype/endpoint/name shifts. Reads return
  the same body version as before.
- **`/update-part` is the wrong path.** That skill handles body /
  template-version changes and explicitly does NOT touch
  `owner_actor` post-#119. If the user wants to reassign ownership,
  you're in the right skill.
