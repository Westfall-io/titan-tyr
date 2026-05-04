---
name: accept-contract-proposal
description: Promote an open titan-tyr contract proposal to the new active version. Use when the user wants to land a previously-proposed contract change — e.g. "accept the contract proposal", "promote 1.1.0-rc1 to active", "make this the new contract". Helps the user pick the contract (by ID, by software, or from a list), shows a unified diff between active and proposal, and POSTs to /contracts/{contract_id}/proposals/{version}/accept. Acceptance changes what every caller sees on `GET /contracts/{contract_id}` — confirm before submitting.
---

# accept-contract-proposal

You are promoting a previously-drafted contract proposal to the new
**active** version. Acceptance is the deliberate counterpart to the
propose flow: propose drafts and submits, this skill lands.

This skill mutates *what every caller sees* on the next
`GET /contracts/{contract_id}`. Treat the final POST as load-bearing:
do not run it without an explicit user confirmation on the exact
contract + version about to land.

## Before you start: confirm THIS side didn't originate the proposal

Cross-team contract review is a two-party handshake: **whoever did NOT
propose is the one who accepts.** If THIS side just ran
`/propose-contract-change` (or otherwise posted the RC you're about
to accept), accepting it now defeats the review — the counterparty
had no chance to push back or counter-propose.

The objection signal from the counterparty is a *higher RC* posted on
the contract. The consent signal is them calling `/accept` (you'll see
`active_version` move forward to the stripped version on the next
`GET /contracts/<id>/proposals`). Neither happens via a GitHub ack —
do not wait for one, but also do not pre-emptively accept your own
proposal in its place.

**Skip this guard only when:**

- Single-operator setup: one human owns both sides of the contract,
  one bearer token, no separate review party.
- Counterparty has explicitly delegated acceptance back to you for
  this proposal.

Otherwise: stop. The counterparty accepts your proposals; you accept
theirs.

How to tell who originated the proposal: check the conversation /
recent activity. If you ran `/propose-contract-change` against this
contract earlier this session, that's almost certainly THIS side.
When in doubt, ask the user.

## Server location

Same env vars as the other titan-tyr skills:

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |
| `TITAN_TYR_ACTOR` | no       | Identity for the X-Actor header. **Strongly recommended** — both content and shift accepts enforce the proposer-doesn't-accept rule (provider v0.16.0+, #38) when both sides set it. Anonymous acceptors get past the rule but skip the structural review. |

If `TITAN_TYR_URL` is unset, **stop and tell the user**:

> `TITAN_TYR_URL` is not set. Set it to the titan-tyr base URL before running this skill, e.g.
> `export TITAN_TYR_URL=http://localhost:8000`.

Don't guess. Don't default to localhost silently.

## Workflow

### 1. Confirm reachability

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/software" -o /dev/null
```

- `200` → continue.
- `401` → wrong token. Stop.
- Connection refused → wrong URL or server down. Stop.

### 2. Resolve the contract

Contracts are addressed by `contract_id` (UUID), not by name. **Don't
ask the user to type a UUID from memory.** Branch on what the user
gave you:

- **They gave a `contract_id` (UUID).** Use it directly. Continue to
  step 3.
- **They gave a software name.** List the contracts touching that
  software:

  ```sh
  curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
    "$TITAN_TYR_URL/parts/{name}/contracts?limit=100"
  ```

  Each entry has `contract_id`, `owner`, `counterparty`, `subtype`,
  `version`, `updated_at`. Render them as a numbered list
  (`owner → counterparty [<subtype>] v<version>`) and ask which one.
  If there's only one, suggest it as the default. `404` → unknown
  part; stop and offer `/find-part`.

- **They gave nothing.** List all contracts (paginated):

  ```sh
  curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
    "$TITAN_TYR_URL/contracts?limit=100"
  ```

  Render `owner → counterparty [<subtype>] v<version>` and ask which
  one. If the result set is paginated (`next` is non-null), warn that
  you've shown the first page and offer to drill in by part name (or
  by `?subtype=<interaction|binding>`) instead.

### 3. List open proposals on the chosen contract

A contract can have **two kinds of open proposal**:

1. **Content proposal** — body change at a new RC version. The
   default and most common path; the rest of this skill walks
   through accepting one.
2. **Subtype-shift proposal** (#33) — structural change to the
   contract's `subtype` and/or `connection_type`. The body is
   untouched; the version is not bumped. A different endpoint, a
   different request shape, but the same proposer-doesn't-accept
   rule applies.

Check both surfaces before deciding which to accept:

```sh
# Content proposals (RCs)
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}/proposals"

# Subtype-shift proposals
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}/subtype-proposals"
```

If a **subtype-shift proposal** is open with `status == "proposal"`,
flag it to the user and branch:

> There's an open subtype-shift proposal on this contract:
>   `<old-subtype>` → `<new-subtype>` (proposed by `<actor>`,
>   "<rationale>"). Accept the shift, accept a content proposal, or
>   list everything?

The shift accept goes through a different endpoint:

```sh
curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "X-Actor: $TITAN_TYR_ACTOR" \
  "$TITAN_TYR_URL/contracts/{contract_id}/subtype-proposals/{proposal_id}/accept"
```

Same proposer-doesn't-accept rule (X-Actor header; pass
`?single_operator=true` for solo setups). On accept, the contract's
`subtype` (and `connection_type` if applicable) flips; body and
version are unchanged. After acceptance, surface the shift's
`body_realign_required` flag — if true, follow up with
`/propose-contract-change` to re-stamp the body.

For content proposals, continue with the rest of this skill.

Show `active_version` and the full list of open content proposals
(version + created_at). They must see what's available before picking.

If both `proposals` and `subtype-proposals` are empty, **stop**:
there is nothing to accept. Tell the user — they likely want
`/propose-contract-change` (or `/propose-contract-subtype-shift`)
first.

**Always re-fetch this list, even if you saw it earlier in the
session.** Cross-team coordination loops mean the counterparty may
have posted a higher RC since you last looked — accepting an older
RC silently overwrites their refinements with stale content.

**Multi-RC for the same target.** If the listing shows multiple RCs
for the same target (e.g. `1.2.0-rc1`, `1.2.0-rc2`), the **latest
RC supersedes** the earlier ones — the earlier RCs are review
artifacts kept for history. Default to the latest. If the user asks
for an older RC, double-check that's intentional; they probably
mean the latest.

### 4. Confirm the target version

Ask which proposal version to accept. Default sensibly:

- If there's a single bare `MAJOR.MINOR.PATCH` proposal, that's the
  natural promote target — suggest it.
- If only RC versions exist (`X.Y.Z-rcN`), ask which RC to accept and
  warn that the server will create a new stable `X.Y.Z` active row
  from the RC body; the RC row itself stays as `proposal` for posterity.
- If both exist for the same target (`X.Y.Z-rc2`, `X.Y.Z-rc3`,
  `X.Y.Z`), the bare version is almost always the right choice — RC
  rows are review artifacts.

Once you've identified the version, **re-check the proposer guard**
(see the "Before you start" section above) against this specific RC.
If it was posted by THIS side, stop here — surface to the user that
the counterparty is the natural acceptor and confirm before
proceeding.

### 5. Show a unified diff vs the active body

The most useful preview is the **diff**, not the full proposal body —
contract proposals often change a single bullet inside a long body.

Fetch the current active body:

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}"
```

The proposal body is already in the JSON from step 3 — pull it from
there. Render a unified diff (Python's `difflib.unified_diff` is
fine):

```python
import difflib
diff = difflib.unified_diff(
    active_markdown.splitlines(keepends=True),
    proposal_markdown.splitlines(keepends=True),
    fromfile=f"active {active_version}",
    tofile=f"proposal {proposal_version}",
    n=3,
)
print("".join(diff))
```

If the diff is empty (proposal body identical to active), surface that
loud — accepting will succeed but is a no-op for readers.

**Also show the diff vs the prior RC** if the proposal you're
accepting is `<target>-rcN` with N > 1 and `<target>-rc(N-1)` (or
any earlier RC of the same target) is in the proposals list. The
"what changed since the last RC" diff is the most useful view when
the counterparty has revised an RC you originally drafted — it
makes their additions reviewable in isolation, not buried inside the
full vs-active diff. Label them clearly:

```
--- changes since rc1 (counterparty's revision) ---
[diff between rc1 and rc2]

--- net change vs active 1.1.1 (what will land) ---
[diff between active and rc2]
```

### 6. Confirm

Ask explicitly:

> About to accept proposal `<version>` on contract `<owner> →
> <counterparty>` (`<contract_id>`) against `$TITAN_TYR_URL`. After
> this, `GET /contracts/<contract_id>` will return the
> `<resulting-active-version>` body shown above. Proceed?

Wait for an unambiguous yes. "Looks good" is yes; silence is not.

Acceptance is reversible only by proposing yet another version that
restores the prior body — there is no "undo accept" endpoint. So a
clean confirmation step matters more here than on propose.

### 7. Submit

```sh
curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "X-Actor: $TITAN_TYR_ACTOR" \
     "$TITAN_TYR_URL/contracts/{contract_id}/proposals/{version}/accept"
```

No request body — the path is the entire input. The `X-Actor`
header carries the acceptor identity for the proposer-doesn't-accept
rule (provider v0.16.0+, #38). If `proposer_actor == X-Actor` on
the proposal row, the call returns `422` with a clear message;
override with `?single_operator=true` only in genuine
single-operator setups:

```sh
curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "X-Actor: $TITAN_TYR_ACTOR" \
     "$TITAN_TYR_URL/contracts/{contract_id}/proposals/{version}/accept?single_operator=true"
```

If `TITAN_TYR_ACTOR` is unset, the rule cannot be enforced and the
accept proceeds — surface a warning to the user that the structural
review gate was bypassed.

### 8. Report

On `200`, summarise the response:

> Accepted. `<subtype>` contract `<owner> → <counterparty>` is now at
> `<active_version>` (promoted from `<promoted_from_version>` at
> `<accepted_at>`).
> Proposer: `<proposer_actor or "anonymous">`. Acceptor: `<acceptor_actor or "anonymous">`.
>
> Verify:
>   `curl -H 'Authorization: Bearer sysmlv2' $TITAN_TYR_URL/contracts/<contract_id>`

If the response carries `single_operator_override: true`, surface it
loudly in the summary:

> ⚠ Accepted under single-operator override (`?single_operator=true`).
> The two-party rule was bypassed for this accept. The flag is recorded
> on the active version row so the bypass is visible in the audit
> trail; mention it explicitly so operators reviewing later see it.

If the response carries `proposer_actor: null` or
`acceptor_actor: null`, surface that too — the rule was unenforceable
and that fact should be visible.

Then flag any companion follow-ups the proposal body called out (e.g.
"once accepted, mimiron should drop its CORS proxy" or similar).
Don't auto-do them — surface them and ask.

## Error handling

| Status | Meaning                                                                   | What to do                                                                  |
| ------ | ------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                                          | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `404`  | Unknown contract or proposal version                                      | Re-list proposals; the version may have been a typo, or the contract id is wrong. |
| `409`  | Version not in `proposal` status (already accepted), or RC's stable target already exists | Re-list proposals; the state has moved since you last looked.               |
| `422`  | Malformed version in the path (`^\d+\.\d+\.\d+(-rc\d+)?$`), contract id not a UUID, or `proposer_actor == X-Actor` without `?single_operator=true` (provider v0.16.0+) | Fix the path. For the two-party rule, have a different actor accept or pass `?single_operator=true`. |
| `5xx`  | Server problem                                                            | Print response body verbatim. Do not retry.                                 |

## Notes

- **RC promotion creates a new row.** Accepting `1.3.0-rc2` produces
  active `1.3.0` (suffix stripped, body copied). The `1.3.0-rc2` row
  stays as `proposal` so the review history is preserved. Earlier RCs
  for the same target also remain as `proposal`.
- **Stable promotion is in-place.** Accepting bare `1.3.0` flips the
  same row from `proposal` → `active`. Same body, same `version`,
  just `accepted_at` set and status changed.
- **"Owner accepts" is governance language, not an API gate.** Every
  registered contract carries a "Change protocol" section that says,
  paraphrasing, "the owner software accepts the proposal." That's a
  *role* statement (which party in the agreement holds the decision)
  — not a permissions check on the endpoint. Any caller with a valid
  bearer token can hit `/accept`. In single-operator setups (one
  human owns both sides of the contract, one bearer token everywhere),
  the agent should run `/accept` itself rather than ask another party
  to do it.
- **Proposer-vs-acceptor is a separate distinction from owner-vs-counterparty.**
  The owner-accepts rule above describes which *role* in the contract
  holds the decision in steady state. The proposer-doesn't-accept rule
  (in the "Before you start" section above) describes the *workflow*
  invariant — whoever just ran `/propose-contract-change` against this
  contract should not be the one accepting that same RC. These can
  cooperate: e.g. mimiron (counterparty) proposes a change, titan-tyr
  (owner) accepts. They can also conflict: titan-tyr (owner) proposes
  a change to its own published surface, but the proposer rule says
  mimiron (counterparty, the one consuming) does the accept — that's
  the cross-team review gate doing its job. In genuinely cross-team
  setups, the proposer rule wins.
- **Contracts only.** This skill drives
  `POST /contracts/{contract_id}/proposals/{version}/accept`. Template
  proposals have a parallel endpoint
  (`POST /templates/{kind}/proposals/{version}/accept`) — that's
  `/accept-template-proposal`'s job.
- **Don't accept stable before the implementation lands.** If the
  proposal commits the provider to behavior the API doesn't yet
  serve (a new endpoint, a new field, a stricter obligation), accepting
  the bare stable version creates a contract that is actively wrong
  about runtime — consumers will read it, build against it, and break.
  Stay on `-rcN` until the provider has shipped the implementation
  and the consumer has verified end-to-end. The owner-side accept
  happens *after* implementation, not before. RC iterations carry no
  such risk because consumers are expected to treat them as
  pre-release.
- **No --data file is needed**, so the JSON-via-file scratch dance the
  register/update skills use does not apply here.
- **There is no reject endpoint.** If you don't like a proposal, the
  response is to counter-propose a higher version that reflects what
  you do want, then accept that. Proposals can't be torn down — they
  stay in `*_versions` for history and drop out of
  `GET .../proposals` once the active version moves past them. By
  design; see DESIGN.md → Open Questions §1.
