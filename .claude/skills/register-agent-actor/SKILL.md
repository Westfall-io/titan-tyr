---
name: register-agent-actor
description: Register a new agent identity in the titan-tyr allowlist (#78). The allowlist gates the human-confirmation rule on destructive accepts — agents listed here are blocked from accepting their own peers' deletion proposals. Use when onboarding a new project's agent ("add the new bot to the allowlist", "register agent X"), or when the human-confirmation gate is letting an agent through it shouldn't. POSTs to `/agent-actors`. To remove one, see the "Revoke" section.
---

# register-agent-actor

You are adding an X-Actor identity to the agent_actors allowlist
that backs the `enforce_human_confirmation` gate. Anything in the
live (non-revoked) set of this table is treated as an agent by the
human-confirmation rule on destructive accepts (today: part
deletion). Anything not in it is treated as a human.

The allowlist exists so two cooperating agents can't bounce a
destructive proposal back and forth and quietly satisfy the
two-party rule with no human in the loop.

## Server location

| Variable          | Required | Purpose                                  |
| ----------------- | -------- | ---------------------------------------- |
| `TITAN_TYR_URL`   | yes      | Base URL. No trailing slash.             |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.     |
| `TITAN_TYR_ACTOR` | no       | X-Actor header. Stored as `registered_by_actor`. Useful as a paper trail of who onboarded the new agent. |

If `TITAN_TYR_URL` is unset, run `/check-titan-tyr-env` first.

## Workflow

### 1. Pick the actor slug

The actor must match the X-Actor header value the agent will send
on its writes. Same slug rule as part names: lowercase letters,
digits, hyphens; 1–64 chars; cannot start or end with a hyphen.

Examples that exist today:
- `titan-tyr` — backend agent for this repo
- `archaedas` — titan-archaedas DevOps agent (note: not `titan-archaedas`)
- `mimiron` — titan-mimiron UI agent

If you're unsure what the agent is sending, check `created_by_actor`
on a recent part or contract it created (`GET /parts?limit=10`).

### 2. Write a description

The description is required (1–200 chars). Include enough that a
future operator can tell at a glance what this identity is. Good:
"titan-foobar build-pipeline agent". Bad: "bot".

### 3. POST it

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer ${TITAN_TYR_TOKEN:-sysmlv2}" \
  -H "X-Actor: ${TITAN_TYR_ACTOR:-}" \
  -H "Content-Type: application/json" \
  --data '{
    "actor": "<slug>",
    "description": "<one-sentence description>"
  }' \
  "$TITAN_TYR_URL/agent-actors"
```

201 → `{actor, description, registered_at, registered_by_actor, revoked_at, ...}`.

### 4. Errors

| Status | Meaning                                              | What to do                                       |
| ------ | ---------------------------------------------------- | ------------------------------------------------ |
| `409`  | Actor already registered (live row exists)           | Confirm with `GET /agent-actors/<slug>`. If you meant to re-register after a revoke, the row is still live — no action needed. |
| `422`  | Slug fails validation, or description empty/too long | Fix and retry.                                   |
| `401`  | Bad bearer token                                     | Stop. Tell user to fix `TITAN_TYR_TOKEN`.        |

## Listing

`GET /agent-actors` — live entries only. `?include_revoked=true`
adds the historical revoked rows. Cursor pagination via `?after=`.

## Revoke (removing an agent)

When an agent identity is decommissioned, revoke (don't delete) so
the audit trail of "who was an agent at what time" survives.

Revoke is **human-only** — an agent X-Actor cannot revoke its
peers (the gate would be trivially bypassable otherwise).

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer ${TITAN_TYR_TOKEN:-sysmlv2}" \
  -H "X-Actor: <human@example.com>" \
  -H "Content-Type: application/json" \
  --data '{"rationale": "<why>"}' \
  "$TITAN_TYR_URL/agent-actors/<slug>/revoke"
```

200 → `{actor, revoked_at, revoked_by_actor, revoke_rationale, ...}`.

| Status | Meaning                                  |
| ------ | ---------------------------------------- |
| `403`  | Acceptor X-Actor is itself in the allowlist (an agent revoking a peer) — have a human revoke instead. |
| `422`  | No X-Actor header on the request.        |
| `404`  | Actor not currently registered (already revoked or never registered). |

After a revoke, the same actor name can be re-registered by
re-posting to `/agent-actors` — that creates a new live row; the
revoked row stays for audit. There can only ever be one *live* row
per actor name.

## Notes

- The allowlist is a single global set. There is no per-project
  scoping today — if you need an agent identity to be considered
  an agent for project A but a human for project B, file an issue;
  the current model doesn't support that.
- Adding an agent does **not** retroactively change the validity
  of any existing accepted proposal. The gate is checked at accept
  time against the live table, so registering or revoking a row
  affects only future accepts.
