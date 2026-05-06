# Authentication

Per-caller bearer tokens, hashed at rest, scoped to a fixed enum
(`read` ⊂ `write` ⊂ `revoke-agent`). Each token carries an actor
identity which the API derives at request time and stamps onto
audit columns (`created_by_actor`, `proposer_actor`, etc).

The legacy single-shared-bearer (`sysmlv2`) path is preserved
during the cutover but defaults to off; a deployer can re-enable
it transitionally by setting an env var (see "Cutover" below).

This doc covers:

1. **Bootstrap** — getting your first admin token on a fresh deploy.
2. **Issuing tokens to consumers** — UI, agents, humans.
3. **Rotation** — replacing a token without downtime.
4. **Leak response** — what to do if a token escapes.
5. **Cutover** — running the legacy and per-caller paths in
   parallel during a migration.

---

## 1. Bootstrap

A fresh deploy has an empty `auth_tokens` table. There's no admin
token yet, so no one can call `POST /auth-tokens` to issue one. The
escape hatch is a server-side CLI that writes directly to the DB.

On the API host, run:

```sh
python -m src.cli issue-token \
    --actor your.name@example.com \
    --description "founder admin token" \
    --scopes revoke-agent
```

Output: a one-time human summary on stderr and the plaintext token
on stdout (last line). **Save the plaintext immediately.** Only the
hash + 8-char prefix are stored — there is no "show me the token
again" recovery path.

Pipe directly into your secret store for the cleanest handoff:

```sh
python -m src.cli issue-token \
    --actor your.name@example.com \
    --description "founder admin token" \
    --scopes revoke-agent \
  | tail -1 \
  > ~/.secrets/titan-tyr-admin   # adjust to your secret store
```

You should now have one admin token (`revoke-agent` scoped).
Subsequent tokens are issued via the API; the CLI is only for the
"chicken and egg" first issuance.

---

## 2. Issuing tokens to consumers

For everything after the bootstrap admin token, use the
`/issue-auth-token` skill (or `POST /auth-tokens` directly).

### Scope guidance

| Consumer type        | Scope            | Why                                                                      |
| -------------------- | ---------------- | ------------------------------------------------------------------------ |
| UI (titan-mimiron)   | `read`           | Render-only by design (project memory). Lowest blast radius if leaked.   |
| Backend agents       | `write`          | Register parts/contracts, propose changes, revoke their own past edits.  |
| Human operators      | `revoke-agent`   | Required to revoke peer tokens and revoke peer agents.                   |

The implication chain (`revoke-agent` ⊇ `write` ⊇ `read`) means a
`revoke-agent` token can also `GET /parts` — you don't need to list
every scope explicitly.

### Via the skill (preferred)

```sh
.claude/skills/issue-auth-token/scripts/issue-auth-token.sh \
    --actor agent-foo \
    --description "build pipeline agent for foo project" \
    --scopes write
```

The skill reads `TITAN_TYR_TOKEN` from `.env` in the current
directory (your admin token) and bails with explicit instructions
if `.env` is missing or the var is unset. See the skill's `SKILL.md`
for the full flow.

### Via the API directly

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "actor": "agent-foo",
    "description": "build pipeline agent for foo project",
    "scopes": ["write"]
  }' \
  "$TITAN_TYR_URL/auth-tokens"
```

The response includes `token` (plaintext, returned exactly once).
Hand it to the consumer via your secret store of choice.

### Scope ceiling

You can only mint tokens with scopes your own token already has.
A `write` admin trying to issue a `revoke-agent` token gets a 403
naming the scope they're missing. Have a higher-scoped admin issue
that one.

---

## 3. Rotation

Token rotation is uneventful: issue a new one, swap it in on the
consumer side, revoke the old one.

```sh
# 1. Issue a replacement, same actor + scopes
NEW=$(.claude/skills/issue-auth-token/scripts/issue-auth-token.sh \
        --actor agent-foo --description "rotated 2026-Q4" --scopes write \
      | tail -1)

# 2. Swap NEW into the consumer's secret store + restart it.
#    (Specifics depend on the consumer.)

# 3. Revoke the old one (look up its id with GET /auth-tokens?actor=agent-foo).
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"rationale": "rotated 2026-Q4"}' \
  "$TITAN_TYR_URL/auth-tokens/<old-token-id>/revoke"
```

Both tokens are valid between steps 1 and 3, so the consumer never
sees a 401. (If you do step 3 before step 2, the consumer's next
request is rejected — order matters.)

There's no automatic rotation today. Rotate when you have reason
to (e.g., a leak, a contractor offboarding, a calendar policy).

---

## 4. Leak response

A leaked token is in someone's hands until you revoke it. Speed
matters. Order:

1. **Revoke the leaked token immediately** via
   `POST /auth-tokens/<id>/revoke`. The hot-path index makes the
   change effective on the next request — no propagation delay.
2. **Audit recent activity** for that actor. Filter
   `GET /parts?match=` and the various history endpoints by
   `created_by_actor` / `proposer_actor` for the leaked actor's
   identity. Anything you don't recognize, treat as suspect.
3. **Issue a replacement** if the consumer still needs one. Same
   actor, same scopes; different token row, different prefix.
4. **Ask why it leaked.** If the consumer's secret store was
   compromised, every other token in that store needs rotation
   too. If a developer pasted it into a chat, document a
   not-again policy.

Per-caller scoping makes this much cheaper than the pre-#81 world,
where one leaked shared bearer compromised every consumer at once.

---

## 5. Cutover (transitional)

During the migration from the legacy shared bearer to per-caller
tokens, both paths can run in parallel:

- **Legacy path (default off):** an admin sets the
  `TITAN_TYR_BEARER_PASSWORD` environment variable on the API host
  to a known value. Any request with `Authorization: Bearer <that
  value>` is accepted and granted **all scopes**; X-Actor falls
  back to whatever the request header carries. This preserves
  pre-#81 behavior for any consumer not yet migrated.
- **Per-caller path:** every other request looks up the bearer's
  sha256 in the `auth_tokens` table.

Order of operations for a clean cutover:

1. Set `TITAN_TYR_BEARER_PASSWORD=<existing-shared-secret>` on the
   API host so existing consumers keep working through the deploy.
2. Issue per-caller tokens to each consumer (UI, each agent, each
   human operator) via the steps in §2.
3. Update each consumer's secret store to use its new per-caller
   token. Restart / reload as needed.
4. Once every consumer is on a per-caller token, **unset**
   `TITAN_TYR_BEARER_PASSWORD` (or set it to empty) on the API
   host. The legacy path now fails closed; only per-caller tokens
   are accepted.
5. (Future, separate PR) The legacy path is removed entirely.

The legacy bearer is shared and broadcast; the per-caller token is
specific. Don't let the cutover's "both work" period drag —
finish step 4 promptly.

---

## What this doc deliberately doesn't cover

- **OAuth / OIDC / external IdP integration.** Not implemented;
  tokens are minted by titan-tyr itself.
- **Per-route ACLs beyond scopes.** A `read` token can read every
  GET endpoint; a `write` token can mutate every POST/PUT. There's
  no per-resource permission model.
- **Token expiry policies.** `--expires-at` is supported per-token
  but there's no global "all tokens expire after N days" rule.
- **Rate limiting per token.** That's #83's territory; deferred.
