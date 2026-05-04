---
name: check-titan-tyr-env
description: Verify the operator's titan-tyr environment is ready for write operations. Checks that TITAN_TYR_URL is set + reachable, TITAN_TYR_TOKEN authenticates, TITAN_TYR_ACTOR is set (and explains the consequences if not), and reports a structured "ready / partial / blocked" verdict. Use as a pre-flight at session start, before chained skill runs, or when another skill complains about missing env. Read-only and non-mutating.
---

# check-titan-tyr-env

You are verifying the operator's titan-tyr environment is configured
correctly before any write operations land. This skill is the
discovery front-end for the rest of the titan-tyr skill family —
once it returns "ready", every other skill's step-1 reachability
probe becomes a redundant safety net rather than the main check.

This skill is **read-only and non-mutating**. Three GETs maximum, no
state changes anywhere.

## Server location

Same env vars as the rest of the family:

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |
| `TITAN_TYR_ACTOR` | no       | Identity for the X-Actor header. Recommended for any session that will run propose/accept/register skills. Without it, the two-party rule is unenforceable on every accept and `created_by_actor` lands null on every register. |

## Workflow

### 1. Check `TITAN_TYR_URL` is set

```sh
echo "$TITAN_TYR_URL"
```

If empty, the verdict is **blocked** — every other titan-tyr skill
will refuse to run. Tell the user explicitly:

> `TITAN_TYR_URL` is not set. Set it to the titan-tyr base URL
> before running any titan-tyr skill, e.g.
> `export TITAN_TYR_URL=http://localhost:18000` (live stack) or
> `export TITAN_TYR_URL=http://localhost:8000` (dev/test stack).

Don't guess. Don't default silently. Stop here.

### 2. Probe reachability

```sh
curl -fsS -o /dev/null -w "%{http_code}" "$TITAN_TYR_URL/health"
```

`GET /health` is unauthenticated, so this is a clean network
liveness probe.

- `200` → server is up. Continue.
- `503` → server is up but its DB is unreachable. Verdict
  **partial** — the server can serve some endpoints but most reads
  and all writes will fail. Surface the response body verbatim.
- Connection refused / timeout / DNS failure → verdict
  **blocked**. Surface the error verbatim. Common causes:
  wrong URL, server not running, wrong port (live is 18000, dev
  is 8000 — see saved memory), VPN required.

### 3. Check `TITAN_TYR_TOKEN` authenticates

```sh
curl -fsS -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer ${TITAN_TYR_TOKEN:-sysmlv2}" \
  "$TITAN_TYR_URL/templates/software"
```

- `200` → token works. Continue.
- `401` → bad token. Verdict **blocked**. If the user has
  `TITAN_TYR_TOKEN` set, surface that they need to fix or unset
  it; if unset, the default `sysmlv2` was rejected — surface that
  the deployment requires a real token.

### 4. Check `TITAN_TYR_ACTOR` is set (recommended, not required)

```sh
echo "$TITAN_TYR_ACTOR"
```

- Set → verdict **ready**.
- Unset → verdict **partial**. Surface explicit consequences:

  > `TITAN_TYR_ACTOR` is not set. The titan-tyr API still accepts
  > anonymous calls, but:
  >
  > - **Propose-side skills** (`/propose-contract-change`,
  >   `/propose-template-change`, `/propose-part-subtype-shift`,
  >   `/propose-contract-subtype-shift`) will record `null` as the
  >   proposer actor. The two-party rule on accept becomes
  >   unenforceable for these proposals.
  > - **Accept-side skills** (`/accept-contract-proposal`,
  >   `/accept-template-proposal`, `/accept-part-subtype-shift`)
  >   cannot identify themselves as the acceptor. The provider
  >   allows the accept to proceed (rule unenforceable), but the
  >   audit trail records `null` for `acceptor_actor`.
  > - **Register-side skills** (`/register-part`,
  >   `/register-contract`) record `created_by_actor: null` on
  >   the new row. No paper trail.
  >
  > To set it for this shell session:
  >
  >   `export TITAN_TYR_ACTOR=your.email@example.com`
  >
  > Or set it permanently in your shell rc. The value is an
  > arbitrary string until real per-caller auth lands; convention
  > is an email or display name that uniquely identifies the
  > human running the session.

### 5. Return the structured verdict

```json
{
  "verdict": "ready" | "partial" | "blocked",
  "checks": {
    "url_set": true,
    "url": "http://localhost:18000",
    "reachable": true,
    "db_reachable": true,
    "token_set": true,
    "token_authenticates": true,
    "actor_set": true,
    "actor": "alice@example.com"
  },
  "warnings": [
    "TITAN_TYR_ACTOR is not set — paper trail will land null on writes"
  ],
  "blockers": []
}
```

- **`ready`** — all four checks pass; every titan-tyr skill should
  work without surprises.
- **`partial`** — at least one non-blocking warning (typically
  `actor_set: false`, sometimes `db_reachable: false` for a
  read-only stack). Skills will still run but with caveats; the
  `warnings` array enumerates them.
- **`blocked`** — at least one entry in `blockers`. Common entries:
  `"TITAN_TYR_URL not set"`, `"server unreachable"`,
  `"token rejected (401)"`. Skills should not be run until the
  blockers are cleared.

## Caller-side composition

`/check-titan-tyr-env` is meant to be called:

1. **At session start** — before any titan-tyr work, run this once
   to confirm the environment. The verdict tells the user (or the
   calling agent) whether to proceed.
2. **From other skills' step 1** — every titan-tyr skill currently
   does its own reachability probe. Those can stay (defense in
   depth), but a calling agent that's already run this skill in
   the session can skip the prompts about what to do when the
   probe fails — this skill already explained.
3. **When something goes wrong** — if a propose / accept skill
   fails with a 401 or connection refused, run this to get a
   structured diagnostic instead of debugging from the failure
   message alone.

## Notes

- This skill never touches state. Three GETs maximum, all to
  read-only endpoints (`/health`, `/templates/software`).
- It does **not** write `TITAN_TYR_*` vars to a shell rc or `.env`
  file — telling the user what to export is enough, and writing
  outside the project would violate the saved filesystem-scope
  rule.
- The `partial` verdict on `TITAN_TYR_ACTOR` unset is intentional,
  not an error. Anonymous operation is supported by the provider;
  the skill just makes the consequences visible so the user opts
  in deliberately rather than by oversight.
- Per saved memory, the live stack lives on port 18000 (token
  `sysmlv2`); 8000 is the dev/test port. If the user's
  `TITAN_TYR_URL` looks wrong for their context, surface the
  distinction in the verdict's `warnings`.
