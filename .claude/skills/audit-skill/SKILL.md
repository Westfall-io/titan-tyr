---
name: audit-skill
description: Review how a recently-invoked skill actually performed in this session. Use after another skill finishes — e.g. "audit how /register-part went", "review the propose-contract-change run", "audit the last skill". Verifies the local skill body matches the canonical version in titan-tyr, reconstructs the run from conversation context, classifies friction/bugs/stale references/missing guidance, and surfaces concrete fix suggestions. Does NOT auto-fix the skill, auto-file issues, replay the run, or audit a stale local copy without explicit override.
---

# audit-skill

You are doing a post-invocation review of a skill that just ran in
this conversation. The point is to surface the gaps that grep-based
sweeps miss: friction the user hit, branches the skill body didn't
cover, instructions that were technically right but read as ambiguous
in context.

This is **read-only and non-mutating**. The audit produces a
structured report and (with user confirmation) drafts of fixes. It
never edits the skill body itself or files issues without explicit
sign-off.

## When to use

After another skill has finished running in this session, when:

- Something felt awkward and you want to capture why before it fades
- A step needed user clarification the skill body didn't anticipate
- A tool call failed and the skill's error guidance didn't match
- You're closing out a session and want to leave the skills better
  than you found them

**Don't use when** the skill body wasn't actually consulted (e.g. the
user invoked the skill name but you skipped reading the SKILL.md).
The audit needs a real comparison between what the skill *said* and
what *happened*.

## Inputs

| Input   | Required | Purpose                                                                                                                                                                          |
| ------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `skill` | yes      | Name of the skill to audit. Must match a directory under `.claude/skills/` (e.g. `register-part`, `propose-contract-change`). Slash prefix optional — strip it before resolving. |
| `notes` | no       | One-liner from the user flagging anything they want probed specifically. Without it, the audit leans on conversation context alone.                                              |

## Workflow

### 0. Freshness check against canonical

The skill body the audit reads must match the **canonical** version
in `github.com/Westfall-io/titan-tyr` on `main`. If you audit a stale
local copy, the friction you classify as a bug may already be fixed
upstream — and any issue you draft is a duplicate that wastes review
cycles.

Fetch the canonical body and diff against the local copy before
loading anything in step 1:

```sh
mkdir -p .scratch
gh api "repos/Westfall-io/titan-tyr/contents/.claude/skills/<skill>/SKILL.md" \
  --jq '.content' \
  | base64 -d > .scratch/audit-canonical-<skill>.md

diff -u .scratch/audit-canonical-<skill>.md .claude/skills/<skill>/SKILL.md
```

Branch on the result:

| Result                                                | What to do                                                                                                                                                                                                                                                                          |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `gh api` returns `404`                                | Skill exists locally but not in canonical — likely a not-yet-upstreamed local skill. Tell the user; ask whether to audit the local-only version or stop.                                                                                                                              |
| `diff` shows no differences                           | Local matches canonical. Continue to step 1.                                                                                                                                                                                                                                         |
| `diff` shows differences AND repo is `titan-tyr` itself | Local has uncommitted changes (or is on a feature branch ahead of `main`) to this skill. Common when working *on* the skill. Ask the user explicitly: audit the local (in-progress) version, or the canonical `main` version? Both are legitimate; the user's intent decides.        |
| `diff` shows differences AND repo is NOT `titan-tyr`   | Local copy is stale relative to canonical. **Stop and surface the diff.** The friction you hit may already be fixed upstream. Recommended path: sync the local copy from canonical, re-run the audited skill, and only audit if the friction persists. Override only on explicit user confirmation. |

Detect "are we in titan-tyr itself" with:

```sh
git config --get remote.origin.url 2>/dev/null | grep -q 'titan-tyr' && echo "in titan-tyr" || echo "downstream"
```

Override message format when stale:

> Your local `.claude/skills/<skill>/SKILL.md` is behind canonical
> (`Westfall-io/titan-tyr@main`). The friction you observed may be
> already fixed upstream — auditing against the stale local would
> likely produce a duplicate of an existing or already-resolved
> issue. Sync first (`gh api ... | base64 -d > .claude/skills/<skill>/SKILL.md`),
> re-run `/<skill>`, and re-invoke this audit if friction persists.
>
> Audit anyway? (y/N)

The override exists for legitimate edge cases — e.g. forks that
intentionally diverge, or auditing a deliberately-pinned older
version. It is **not** a default; the default is to stop.

### 1. Load the skill body

Read `.claude/skills/<skill>/SKILL.md` in full. The audit needs the
complete body to compare against the run, not a summary.

If the path doesn't exist, **stop and ask** — the user may have given
a stale name (skill renamed, never existed) or a typo. List the
available skill directories so they can re-pick:

```sh
ls .claude/skills/
```

### 2. Reconstruct the run from conversation context

Walk back through recent turns of *this* conversation to find:

- **Inputs** the user provided (or the skill inferred)
- **Steps** the skill took, in order — note any it skipped or
  reordered vs. the workflow in the SKILL.md
- **Clarification points** — every place the user had to answer a
  question the skill body could have anticipated
- **Tool failures** — any error returned by curl, the API, or another
  tool, with the skill's response to it
- **Confirmations** — places where the skill paused for user sign-off
- **Silent gaps** — situations the skill didn't cover where you
  improvised; these are the most valuable to surface

If the conversation context doesn't cover the run (compaction
happened, the run was in a different session), **say so** rather than
fabricating a reconstruction. The audit needs ground truth.

### 3. Classify each gap

For every divergence between what the skill body said and what
actually happened, classify as one of:

| Class               | Meaning                                                                                                                       | Example                                                                                                |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| **Bug**             | Skill instruction is wrong — wrong endpoint, wrong field name, will-always-fail recipe.                                       | `/find-part` told curl to hit `/software` but the route is `/parts` (titan-tyr#27).                    |
| **Friction**        | Instruction is technically right but caused a clarification round, an extra tool call, or a moment of ambiguity.              | Step said "ask the user which proposal" without mentioning the natural default for single-RC cases.    |
| **Missing guidance**| Situation didn't fit any documented branch and you improvised.                                                                | Skill didn't cover what to do when the active body's stamp is *newer* than the active template (race). |
| **Stale**           | Instruction refers to something that has been renamed/restructured since the skill was last edited.                           | Stamp pattern `contract@X.Y.Z` matched the pre-#24 kind name.                                          |

For each gap, capture: **where** in the SKILL.md (section + line if
useful), **what** the skill said, **what actually happened**, **what
class** it falls in.

### 4. Distinguish session-specific from generalizable

Not every awkward moment is a skill bug — sometimes it's an unusual
input that no reasonable skill body could have anticipated. Before
drafting fixes, **walk the gaps with the user** and ask which are
worth acting on:

> Found N gaps. Worth treating as skill issues:
>
> 1. [Bug] `/find-part` step 2 hits `/software` instead of `/parts` — confirmed broken
> 2. [Friction] `/accept-template-proposal` step 1 still lists 2 kinds, missed the post-#24 expansion to 4
> 3. [Missing guidance] `/propose-contract-change` doesn't cover the template-acceptance race we just hit
> 4. [Session-specific] User wanted the proposal body in a non-standard format; not a skill issue
>
> Confirm which to draft fixes for.

This step is **load-bearing**. Skipping it means filing noise as
issues; over-applying it means real bugs go undocumented.

### 5. Draft fixes

For confirmed gaps, produce one of:

- **Inline edit suggestion** — small, clearly-scoped wording or
  step-order change. Show the diff in the audit report; do not
  apply it. The user accepts or rejects.
- **GitHub issue body** — change is large, restructures the workflow,
  or needs review from another party. Draft the body in the audit
  report; do not file it. The user runs `gh issue create` themselves
  (or asks you to).

Use the existing skill-issue convention from titan-tyr#27-#30:
sections for "Bugs", "Missing capability", "Acceptance" with
checkboxes.

**Do not** auto-apply edits or auto-file issues. The forcing function
of this audit is the user's deliberate review of each gap, not a
batch commit.

### 6. Report

Single structured summary at the end:

```
Audit of /<skill> (<turns> conversation turns reconstructed):

Gaps found:
  - [Bug] <one-liner> → <action: inline edit | issue draft>
  - [Friction] <one-liner> → <action>
  - [Missing guidance] <one-liner> → <action>

Drafted edits: <count>      (apply with explicit user confirmation)
Drafted issue bodies: <count> (file with `gh issue create` when ready)

Skipped as session-specific: <count>
```

If the audit found nothing actionable, say so explicitly:

> No skill gaps surfaced. The run followed the workflow as written;
> any friction was input-specific.

A clean audit is a real outcome, not a failure mode.

## What this skill does NOT do

- **No auto-fixing.** Every fix decision goes back to the user. Inline
  edits are *drafted*, not applied.
- **No auto-filing.** Issue bodies are *drafted*, not posted. The
  user runs `gh issue create` when ready.
- **No replay or re-execution.** This is a review of what already
  happened in this conversation, not a rerun of the audited skill.
- **No coverage scoring or quality metrics.** The output is concrete
  gaps, not a rubric or a percentage.
- **No coupling to specific skills.** This skill reads
  `.claude/skills/<skill>/SKILL.md` and conversation context — adding
  a new skill to the repo Just Works without touching this one.
- **No fabrication when context is gone.** If conversation compaction
  or a session boundary swallowed the run, say so and stop. Don't
  reconstruct from imagination.
- **No auditing a stale local skill body.** Step 0 enforces this:
  if the local copy diverges from canonical and you're not in the
  `titan-tyr` repo itself, stop and surface the diff. Auditing a
  stale local would dutifully classify already-fixed bugs as new ones
  and draft duplicate issues. Override only on explicit user
  confirmation, never as a default.

## Notes

- **Audit your own audit.** If `/audit-skill` itself feels awkward
  to use, that's the most important gap to surface — invoke it on
  itself: `/audit-skill audit-skill`.
- **Friction reports compound.** One friction item per audit feels
  like noise; ten across ten audits is a pattern. Surface patterns
  the user may not see in any single run.
- **The reconstruction in step 2 is the load-bearing capability.**
  If the conversation context is too thin to reconstruct the run
  faithfully, the rest of the workflow is built on sand. Bias toward
  saying "I can't reconstruct this faithfully" over confident
  hallucination.
- **No env vars needed for the audit itself.** Unlike the rest of the
  titan-tyr skills, this one doesn't hit the titan-tyr API — it reads
  files in the repo and conversation context. `TITAN_TYR_URL` is
  irrelevant here. The freshness check in step 0 does need `gh` auth
  to read from `Westfall-io/titan-tyr`; if `gh auth status` shows no
  token, prompt the user to log in (`gh auth login`) before retrying.
