# Project skills

Skills here are auto-discovered by [Claude Code](https://claude.com/claude-code)
when you run it from the titan-tyr repo root. Type `/<skill-name>` to invoke.

| Skill                                                            | What it does                                                          |
| ---------------------------------------------------------------- | --------------------------------------------------------------------- |
| [`register-part`](./register-part/SKILL.md)               | Register a part with a running titan-tyr instance. Optional `project` tag (#44). |
| [`register-contract`](./register-contract/SKILL.md)               | Register a new interface contract between two parts already in titan-tyr. Picks owner+counterparty via `?match=`, fills the contract template, POSTs to `/contracts`. Optional `project` tag (#44). |
| [`register-project`](./register-project/SKILL.md)                 | Register a new project tag (#44). Projects group parts and contracts so the UI can filter to one project at a time. |
| [`list-projects`](./list-projects/SKILL.md)                       | Read-only list of registered projects with part / contract counts. Use to discover valid project slugs before tagging. |
| [`update-part`](./update-part/SKILL.md)                   | Append a new version to an already-registered part. Detects template-version drift and helps migrate. Supports project (re)assignment via the optional `project` field. |
| [`learn-part`](./learn-part/SKILL.md)                     | Look up everything titan-tyr knows about a registered part — description, ticket-filing target, contracts. Read-only; returns structured JSON. |
| [`find-part`](./find-part/SKILL.md)                       | Resolve a colloquial label or partial name (e.g. "front end") to a canonical part slug via `?match=`. Read-only; returns structured JSON. |
| [`propose-template-change`](./propose-template-change/SKILL.md)   | Draft and POST a proposal to update one of titan-tyr's templates (`software`, `container`, `interaction`, `binding`). Does not auto-accept. |
| [`propose-contract-change`](./propose-contract-change/SKILL.md)   | Draft and POST a proposal to amend an existing interface contract. Helps pick the contract, opens the active body for in-place editing, shows a unified diff. Does not auto-accept. |
| [`accept-template-proposal`](./accept-template-proposal/SKILL.md) | Promote an open template proposal to the new active version. Mutates what every caller sees on the next `GET /templates/{kind}`. |
| [`accept-contract-proposal`](./accept-contract-proposal/SKILL.md) | Promote an open contract proposal to the new active version. Helps pick the contract (by id, by part name, or from a list), shows a unified diff vs the active body, then POSTs accept. |
| [`audit-skill`](./audit-skill/SKILL.md)                           | Review how a recently-invoked skill actually performed in this session. Reads the skill body, reconstructs the run from conversation context, classifies bugs/friction/stale/missing-guidance gaps, and drafts fixes. Read-only — no auto-apply, no auto-file. |

## Configuration

These skills hit a live titan-tyr API. Set the location via environment
variables before invoking:

```sh
export TITAN_TYR_URL=http://localhost:8000   # required, no trailing slash
export TITAN_TYR_TOKEN=sysmlv2               # optional; default sysmlv2
```

## Resuming work in flight

Most contract and template changes are multi-step coordination loops
across two parties (a propose / iterate / accept handshake, often
mirrored by a cross-repo issue). When you pick up a task that was
gated on someone else — your previous proposal is in flight, you
filed an issue and the other team responded, you posted an RC and
the counterparty was reviewing — **refresh state before acting**:

- **Re-list contract proposals** (`GET /contracts/{id}/proposals`).
  The counterparty may have posted a higher RC superseding yours,
  closed out by accepting, or otherwise moved the state since you
  last looked.
- **Re-fetch the linked GitHub issue** if one exists. New comments
  there are often the "I noticed X, can you fix Y" signal that
  changes what your next step should be.
- **Skim recent commits** on the relevant branch / repo if the work
  involved code on the other side.

Half the value of these skills is just remembering to check before
proceeding. The propose / accept skills both re-fetch state in their
early steps for this reason — don't skip those steps because "I
already saw it earlier in the session."

## Common pitfalls

- **Contract changes go through `POST /contracts/{id}/proposals`,
  not GitHub issues.** A "we need to change the contract" complaint
  filed as an issue on titan-tyr (or any consumer/provider repo) is
  the wrong shape — file a proposal against the contract instead.
  GitHub issues are the right place for *coordination*
  (notifications, review threads, cross-team back-and-forth) but
  they're a layer on top of the contract endpoint, not a substitute
  for it.
- **The propose / accept skills are deliberately separated.** Don't
  collapse them into a single auto-accept call. The boundary IS the
  review gate. (`/propose-contract-change` enforces this; the rare
  case for collapsing — single-operator setup — is documented
  there.)
- **The proposer doesn't accept their own proposal.** Cross-team
  review is a two-party handshake; whoever did NOT propose accepts
  (or counter-proposes). See `/accept-contract-proposal` →
  "Before you start" for the full protocol.

## Why env vars (and not a config file)

- **Per-shell scope** matches "I'm pointing at staging right now" without
  editing files.
- **No file to forget about** — `unset TITAN_TYR_URL` clears the state
  cleanly.
- **CI-friendly** — pipelines already inject env vars; no template
  rendering needed.
- **Composable** with the API's bearer header, which itself is just a
  string in env.

A config file would add a precedence question (file vs env vs flag) and
state to clean up. Re-evaluate if/when there are more than three settings.
