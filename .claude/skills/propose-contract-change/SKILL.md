---
name: propose-contract-change
description: Propose a change to an existing titan-tyr interface contract. Use when the user wants to amend the agreement between two parts — e.g. "propose a change to the X↔Y contract", "draft a contract update", "we need to add a CORS obligation". Helps pick the contract (by id, by part name, or from a list), opens the active body for in-place editing, shows a unified diff, picks a version, and POSTs to /contracts/{contract_id}/proposals. Does NOT accept the proposal — acceptance is a deliberate separate step via /accept-contract-proposal.
---

# propose-contract-change

You are drafting a proposed change to an existing interface contract.
Contracts live in Postgres and evolve through a propose / accept / RC
flow — same machinery as templates. This skill **creates the
proposal**; it never accepts. Acceptance is the user's explicit next
step (`/accept-contract-proposal`).

This skill is for **amending an existing contract**. Initial contract
creation goes through a register skill (currently raw `POST /contracts`
— skill tracked separately).

## Server location

Same env vars as the other titan-tyr skills:

| Variable          | Required | Purpose                                          |
| ----------------- | -------- | ------------------------------------------------ |
| `TITAN_TYR_URL`   | yes      | Base URL of the API. No trailing slash.          |
| `TITAN_TYR_TOKEN` | no       | Bearer token. Defaults to `sysmlv2`.             |

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
- **They gave a part name.** List the contracts touching that part:

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

### 3. Fetch the current active body

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}"
```

This is the body the proposal will be **amending**. Save it to
`.scratch/contract-<contract_id>-active.md` so you have a clean
starting point for the edit and a stable reference for the diff
preview later.

Note the active `version` from the response — you'll need it to pick a
strictly-greater proposal version in step 5.

### 4. Check for existing proposals

```sh
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/contracts/{contract_id}/proposals"
```

Surface `active_version` and any open `proposals`. Two reasons:

- **Floor for the new version.** The strictly-greater check on the
  server uses the max across active *and* open proposals. If
  `1.1.0-rc2` is already open, the new version must beat it.
- **Iteration vs new round.** If there's already an open
  `<target>-rc1` and the user is making refinements to that same
  proposal, the right move is `<target>-rc2`, not jumping to a
  brand-new target. Ask which they intend.

### 4b. Check the matching template's state

The contract carries a template-version stamp; the new body in step 5
will need to be checked against it. Fetch the template state now so
you have it in hand:

```sh
# subtype came from step 3's contract body (interaction | binding)
curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  "$TITAN_TYR_URL/templates/<subtype>/proposals" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('active:', d['active_version'])
print('open proposals:', [p['version'] for p in d['proposals']])
"
```

You will use the active version in step 5 (drift check) and use the
open-proposals list to detect the **template-acceptance race** — the
case where a contract body uses terminology or stamp from a template
version that hasn't been accepted yet. See step 5.

### 5. Apply the change

Default to **in-place editing** of the active body, not starting from
scratch. A typical contract proposal touches one bullet inside a long
body — making the user re-paste the whole thing is friction.

Common shapes:

- **Natural-language edit** — "add a CORS provider obligation between
  the JSON contract bullet and the error shape bullet." Apply the
  edit to the saved active body and produce the **complete new
  body**. Save to `.scratch/contract-<contract_id>-<version>-rc1.md`.
- **Diff or partial fragment** — apply against the active body to
  produce the complete new body.
- **Full new body** — user pastes or hands you the entire markdown.
  Use it as-is (modulo a sanity check).

titan-tyr stores **full markdown bodies**, not diffs. Whatever shape
the user gave you, the artifact you POST is the entire new body.

**Template-stamp check.** Contract bodies carry a stamp at the top
matching the contract's subtype:

- `<!-- template: interaction@X.Y.Z -->` for `interaction` contracts
- `<!-- template: binding@X.Y.Z -->` for `binding` contracts
- `<!-- template: contract@X.Y.Z -->` is **legacy** — the `contract`
  template kind was renamed to `interaction` in titan-tyr v0.10.0
  (#24) and a sibling `binding` kind was added. Any modern contract
  carrying `contract@` is by definition stamp-stale and must be
  re-stamped to `interaction@` (or `binding@` if it's actually a
  binding contract that escaped the rename).

Compare the proposed body's stamp against the template state from
step 4b:

| Stamp state                                                 | What to do                                                                                                                                                                                                                                              |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Stamp `kind` is `contract` (legacy)                         | Re-stamp to `<subtype>@<active-template-version>`. This is a structural migration; surface it as such, but do not skip it — a modern contract cannot keep the legacy stamp.                                                                              |
| Stamp `kind` matches subtype, version == active             | No drift. Continue.                                                                                                                                                                                                                                     |
| Stamp `kind` matches subtype, version older than active     | Body is using stale template terminology. Mention to the user; offer to re-stamp. Do not silently re-stamp.                                                                                                                                              |
| Stamp `kind` matches subtype, version newer than active     | Body's stamp points at a template version that **isn't active yet**. See template-acceptance race below.                                                                                                                                                  |

**Template-acceptance race.** If the proposed contract body's stamp
references a template version that exists only as an open *template*
proposal (not yet accepted), and you POST the contract proposal now,
the body will sit in titan-tyr referencing a stamp that resolves to no
active template. If the contract proposal then gets accepted before
the template proposal does, the active body bakes in a phantom stamp
— and you can't fix it via supersede (the stable target's RC slot is
gone), only via a stamp-only patch-bump on the next version.

The fix is ordering: **accept the template proposal first**, then
propose the contract change. If you can't (separate parties, separate
review windows), at minimum add an explicit acceptance-order note to
the contract proposal's body so the human acceptor knows to wait.

Stop and warn the user before proceeding when this case is detected.

### 6. Choose a version

The new version must be **strictly greater than every existing version
on this contract** (active *plus* any open proposals). Pick a bump
that matches the user's intent:

| Change shape                                                                     | Bump                                                     |
| -------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Breaking — silently breaks deployed consumers (path renamed, required field changes shape, pagination semantics shift) | MAJOR (e.g. `1.2.3` → `2.0.0`)                          |
| Additive — new provider obligation, new optional consumer commitment, expanded surface | MINOR (e.g. `1.2.3` → `1.3.0`)                          |
| Clarification — wording fix, typo, no behavior change either side                | PATCH (e.g. `1.2.3` → `1.2.4`)                          |
| Iterating with the counterparty before locking in                                | append `-rcN` to the target (`1.3.0-rc1`, `1.3.0-rc2`)  |

If the user expects review rounds before the change goes live (the
common case for cross-team contracts), **recommend RC iterations** —
start with `<target>-rc1`, then bump the RC number on each revision,
then propose the bare `<target>` once both sides agree. Acceptance of
the bare `<target>` will create the new active version; the RCs stay
in the database for posterity.

**Implementation-pending changes start as `-rc1`, not bare stable.**
If the proposal commits the provider to behavior the API doesn't yet
serve (a new endpoint, a new field, a stricter obligation),
post as `<target>-rc1` even when there's no negotiation expected.
Bare stable comes after the provider has implemented and the consumer
has verified end-to-end — accepting stable earlier creates a contract
that lies about runtime. (See the symmetric guard in
`/accept-contract-proposal`.)

If you can compute "the next sensible version" given the user's intent
(e.g. they said "this is breaking" and active is `1.2.0`), suggest it
and let the user override.

### 7. Preview before submitting

Show **two things** before asking for confirmation:

1. **A unified diff** between the saved active body and the new body
   you intend to propose. Use Python's `difflib`:

   ```python
   import difflib
   diff = difflib.unified_diff(
       active.splitlines(keepends=True),
       proposed.splitlines(keepends=True),
       fromfile=f"active {active_version}",
       tofile=f"proposed {new_version}",
       n=3,
   )
   print("".join(diff))
   ```

   The diff is what reviewers actually care about — proposal bodies
   are usually long but the change is often a single bullet.

2. **The version you intend to submit**, with a one-line rationale
   (which bump and why).

Ask "ready to propose?" Do not POST until the user confirms. If they
want changes, iterate — re-show the diff after each edit.

### 8. Submit

Build the JSON via a tool, not shell heredocs or `-d "..."`. Contract
bodies will contain backticks, pipes, asterisks, double quotes, and
unicode — `--data @file.json` written by Python sidesteps every
shell-escaping landmine.

**Scratch files must live inside the project.** Do not write to `/tmp`,
`$HOME`, or any path outside the working directory. Use `.scratch/` at
the repo root (gitignored — create it if it doesn't exist) and clean up
after.

```sh
mkdir -p .scratch
python3 -c "
import json, pathlib
print(json.dumps({
    'version': 'X.Y.Z',  # or 'X.Y.Z-rcN'
    'markdown': pathlib.Path('.scratch/contract-<contract_id>-<version>-rc1.md').read_text(),
}))
" > .scratch/contract-<contract_id>-<version>-rc1.json

curl -fsS -X POST \
     -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     -H "Content-Type: application/json" \
     --data @.scratch/contract-<contract_id>-<version>-rc1.json \
     "$TITAN_TYR_URL/contracts/{contract_id}/proposals"
```

### 9. Report the API result

On `201`, summarise:

> Proposed `<version>` for `<subtype>` contract `<owner> → <counterparty>`
> (`<contract_id>`). Status: `proposal`.
>
> List open proposals:
>   `curl -H 'Authorization: Bearer sysmlv2' $TITAN_TYR_URL/contracts/<contract_id>/proposals`

If the proposal is RC, mention that the typical next step is iterate
(`-rc2`, `-rc3`) until both sides agree, then propose the bare
`<target>` and accept that.

If the change has cross-repo implications (e.g. a counterparty needs
to file a tracking issue, drop a workaround, etc.), surface them —
they're often in the proposal's body but worth restating.

### 10. Notify the counterparty

Contract proposals are visible via the API but the counterparty's
developer doesn't poll. Without a GitHub notification on their side,
the proposal sits unreviewed and the loop stalls. Pair every
cross-team proposal with a comment on the counterparty's repo.

**Skip this step only if** the user is operating both sides of the
contract solo (one human, one repo for both). Default is to notify.

a. **Identify the counterparty repo.** The counterparty part's
   `repo_uri` is a GitHub URL — fetch:

   ```sh
   curl -fsS -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
     "$TITAN_TYR_URL/parts/<counterparty_name>" \
     | python3 -c "import json,sys; print(json.load(sys.stdin)['repo_uri'])"
   ```

   Convert to `<owner>/<repo>` form for `gh` (e.g.
   `https://github.com/Westfall-io/titan-mimiron` →
   `Westfall-io/titan-mimiron`).

b. **Find the linked issue.** Look in the proposal body and recent
   conversation for a referenced issue in the counterparty repo (often
   a `<repo>#N` link in the changelog, or the consumer-side feature
   that motivated this proposal). If there's an obvious one, use it.
   If unsure, list open issues and ask:

   ```sh
   gh issue list --repo <owner>/<repo> --state open --limit 10
   ```

c. **Comment on the linked issue** with: contract id, the new RC
   version, what changed in 1–2 lines (call out anything beyond what
   the linked issue originally scoped), and the inspect URL. Keep it
   short — diff and decision-making belong on the contract endpoint,
   not in the GitHub thread.

   ```sh
   gh issue comment <number> --repo <owner>/<repo> --body "$(cat <<'EOF'
   ## Update from titan-tyr

   Posted contract proposal `<version>` for contract
   `<contract_id>`.

   What changed vs `<active_version>`: <one-or-two-line summary>

   Inspect:
   ```
   GET /contracts/<contract_id>/proposals
   ```
   EOF
   )"
   ```

d. **No obvious linked issue?** File a new one against the counterparty
   repo:

   ```sh
   gh issue create --repo <owner>/<repo> \
     --title "titan-tyr contract <contract_id> — review <version>" \
     --body "<same body as above>"
   ```

**Do not auto-accept your own proposal.** The propose/accept boundary is
the contract review gate, and the counterparty is the side that
accepts (see `/accept-contract-proposal`). After step 10, your job ends
— wait for the counterparty to either accept (`active_version` moves
forward) or counter-propose (a higher RC appears on the contract).
Even if the user appears to want it landed immediately, surface that
the counterparty is the natural acceptor; only run
`/accept-contract-proposal` yourself if the user explicitly tells you
to (single-operator setup, or counterparty has delegated).

## Error handling

| Status | Meaning                                                          | What to do                                                                  |
| ------ | ---------------------------------------------------------------- | --------------------------------------------------------------------------- |
| `401`  | Bad bearer token                                                 | Stop. Tell user `TITAN_TYR_TOKEN` is wrong.                                 |
| `404`  | Contract id not found                                            | Re-resolve in step 2; the id may be wrong.                                  |
| `409`  | `version` not strictly greater than latest (active + proposals)  | Bump beyond the current max. Suggest a value computed from step 4's data.   |
| `422`  | Malformed `version` or contract id not a UUID                    | Format is `^\d+\.\d+\.\d+(-rc\d+)?$`. No `alpha`/`beta` suffixes.           |
| `5xx`  | Server problem                                                   | Print response body verbatim. Do not retry.                                 |

## Notes

- A common pattern: open with `<target>-rc1`, gather counterparty
  feedback (often via a GitHub issue on their repo), iterate
  (`<target>-rc2`, `<target>-rc3`), then propose the bare `<target>`
  and accept. All RCs are preserved in the database for history; only
  the final stable becomes active.
- **Contracts amend in-place; templates do too.** The flow is
  identical to `/propose-template-change`; the differences are
  addressing (contract id vs template kind) and the source body
  (active contract vs active template).
- **There is no withdraw or reject.** Once a proposal is POSTed it
  stays in the database. If you decide the proposal is wrong before
  it's accepted, propose a higher version that reflects what you
  actually want and accept that. The dangling earlier proposal is
  preserved for history and drops out of `GET .../proposals` once the
  active version moves past it. Same on the receiver side — the
  response to a proposal you don't like is a counter-proposal, not a
  rejection.
- **No initial-creation here.** This skill amends contracts that
  already exist. Initial `POST /contracts` is a separate path
  (currently raw; skill tracked separately).
