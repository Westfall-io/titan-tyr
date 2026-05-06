---
name: issue-auth-token
description: Issue a per-caller auth token for a specific actor + scope set (#81 + #82 + #84). Use when onboarding a new consumer (UI, agent, human operator) or rotating an existing token. Wraps POST /auth-tokens. Requires an admin token in .env (TITAN_TYR_TOKEN). The plaintext of the freshly issued token is printed once and never recoverable — pass it to the consumer immediately. To revoke a token, see "Revoke" below.
---

# issue-auth-token

You are minting a per-caller auth token. Each consumer (the UI, each
agent, each human operator) holds a unique token; the token carries
the actor's X-Actor identity and a scope set
(`read` ⊂ `write` ⊂ `revoke-agent`). When the token is used, the
auth dependency derives X-Actor from the row — the legacy
header-asserted X-Actor is ignored.

This skill cannot mint a scope above the admin token's own. A
`write` admin can issue read or write tokens; only a `revoke-agent`
admin can issue a `revoke-agent` token.

## Server location

| Variable        | Required | Purpose                                   |
| --------------- | -------- | ----------------------------------------- |
| `TITAN_TYR_URL` | yes      | Base URL. No trailing slash.              |

## .env (current directory)

| Key                | Required | Purpose                                                                 |
| ------------------ | -------- | ----------------------------------------------------------------------- |
| `TITAN_TYR_TOKEN`  | yes      | The admin bearer token plaintext. Used as the request's Authorization. |

If `.env` is missing or doesn't define `TITAN_TYR_TOKEN`, the script
**bails with explicit instructions** for both the "first deploy"
case (run the bootstrap CLI on the API host) and the "another admin
exists" case (ask them to issue you one). Read the error message;
follow the instructions verbatim.

## Workflow

### 1. Decide the actor + scopes

The actor is an X-Actor slug — the value the consumer's writes will
appear under in `created_by_actor` columns. Same slug rule as part
names: lowercase letters / digits / hyphens; 1–64 chars; no leading
or trailing hyphen.

Scope guidance:

| Consumer type            | Scope             | Reason                                                 |
| ------------------------ | ----------------- | ------------------------------------------------------ |
| Read-only client (UI)    | `read`            | Cannot mutate anything. Lowest blast radius if leaked. |
| Backend agent            | `write`           | Registers parts/contracts, proposes changes.           |
| Human operator (admin)   | `revoke-agent`    | Required to revoke peer agents and other tokens.       |

Don't grant `revoke-agent` to agents. The whole point is to keep
the destructive-accept gate (and the auth-token revoke gate) in
human hands.

### 2. Run the script

```sh
.claude/skills/issue-auth-token/scripts/issue-auth-token.sh \
  --actor <slug> \
  --description "<one-line; what is this token>" \
  --scopes <read|write|revoke-agent>[,...] \
  [--expires-at 2026-12-31T23:59:59Z]
```

The script prints a human-readable summary on **stderr** and the
plaintext token alone on **stdout** (last line). To capture into a
secret store:

```sh
.claude/skills/issue-auth-token/scripts/issue-auth-token.sh \
  --actor agent-foo --description "..." --scopes write \
  | tail -1 \
  | <pipe to your secret store>
```

### 3. Hand off the plaintext immediately

The plaintext is returned exactly once. The DB stores only the
sha256 hash and the first 8 chars (the prefix, used by ops to
identify "which token is this"). If the operator loses the
plaintext, the only remedy is to revoke that token and issue a new
one — there is no "show me the token again" endpoint.

### 4. Errors

| Status | Meaning                                                          | What to do                                                                              |
| ------ | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `403`  | Admin token's scopes are below the requested scopes              | Request fewer scopes or have a higher-scoped admin issue this token.                    |
| `422`  | Slug fails validation, scope unknown, or empty description       | Fix and retry.                                                                          |
| `401`  | Admin token in `.env` is invalid, revoked, or expired            | Verify with `GET /auth-tokens/<your-token-id>` (need a working admin to do that) or have an admin reissue. |

## Listing

`GET /auth-tokens` (read scope) — never returns plaintexts. Filter
to one actor's tokens with `?actor=<slug>`. Add `?include_revoked=true`
to surface historical revoked rows.

## Revoke

Token revoke is human-only — requires the `revoke-agent` scope.

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"rationale": "<why>"}' \
  "$TITAN_TYR_URL/auth-tokens/<token-id>/revoke"
```

The revoked row stays in the DB for audit. Re-issuing for the same
actor creates a new live row with a new id.

## Notes

- **Bootstrap.** The first admin token on a fresh deploy must come
  from the server-side CLI: `python -m src.cli issue-token` on the
  API host. Once one admin token exists, every subsequent token
  can be issued via this skill.
- **Cutover from the legacy shared bearer.** During the transition
  period, the legacy bearer (from `TITAN_TYR_BEARER_PASSWORD` env
  var) is also accepted and grants all scopes. New consumers
  should start on per-caller tokens; existing consumers can
  rotate at their own pace. Drop the env var on the API host
  once everyone has migrated.
- **No expiry by default.** Long-lived agent tokens are fine. Set
  `--expires-at` for short-lived ops tokens (e.g. a contractor
  pulling a one-day audit dump).
