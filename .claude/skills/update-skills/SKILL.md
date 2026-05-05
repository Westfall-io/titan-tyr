---
name: update-skills
description: Pull or check the titan-tyr skill catalog from github.com/Westfall-io/titan-tyr@main against the local .claude/skills/ directory. Use when the user wants to refresh, install, or re-sync the titan-tyr skills (e.g. "update my titan-tyr skills", "sync the latest skills", "I'm getting a stale-skill error", "refresh the catalog"), or when they want to *check* whether their local copies have drifted from upstream before doing work ("are my skills stale?", "did anything change upstream?"). Sync mode is a destructive overwrite — local edits to pulled skill files are lost. titan-tyr@main is the source of truth; file feedback as a titan-tyr issue, not by hand-editing the pulled copy.
---

# update-skills

Pull the titan-tyr skill catalog into the consumer repo. Each skill's
helper scripts are co-located with the skill itself
(`.claude/skills/<name>/scripts/`), and cross-cutting helpers used
by multiple skills live in `.claude/skills/_shared/scripts/`. The
pull never touches the consumer's top-level `scripts/` dir.

This skill is for **downstream consumers** of titan-tyr — repos whose
agents call the titan-tyr API and need the propose / accept / register /
learn skill family locally. It is **not** for the titan-tyr repo itself;
the canonical source lives there and the pull would be a self-overwrite.
The sync script refuses to run if it detects it's executing inside
`Westfall-io/titan-tyr`.

## When to use

- The user asks to update / sync / refresh / install titan-tyr skills.
- The user wants to *check* whether their local copies have drifted from
  upstream — use `--check` mode (read-only, no writes; exits 1 on drift).
  Useful as a pre-flight before running a flow that depends on a specific
  skill being current, or as a periodic cron / commit-hook check.
- A different titan-tyr skill failed in a way that suggests a stale local
  copy: missing flag, missing endpoint, signature mismatch, "X-Actor not
  recognized" when the API documents it. Run `--check` to confirm drift,
  then re-sync without the flag and retry the failing skill.

## When NOT to use

- The user wants to *propose a change* to a skill body. File a titan-tyr
  issue instead — this skill overwrites local edits, it does not push.
- The user is working inside titan-tyr itself. The repo's own skills are
  the source of truth there. The script will refuse.
- The user's environment lacks `gh` (it's required for authed API access
  to private repos). Tell them to install it first; do not fall back to
  unauthed `curl` against `raw.githubusercontent.com` — the repo is
  private and that endpoint will 404.

## Workflow

### 1. Pre-flight

Confirm the operator has the toolchain:

```sh
gh --version >/dev/null && gh auth status && python3 --version >/dev/null
```

If `gh auth status` reports unauthenticated, stop and tell the user to
run `gh auth login` first.

If the user is in the titan-tyr repo itself, stop here and tell them —
the sync script will refuse, but it's clearer to call this out up front.
Detect with:

```sh
git remote get-url origin 2>/dev/null
```

### 2. Pick a mode

**Drift check (read-only).** Confirm whether the local catalog matches
upstream. No writes. Exits 1 if anything would change on a real sync.

```sh
.claude/skills/update-skills/scripts/sync-titan-tyr-skills.sh --check
```

Output is one line per file with a status column:

| Status    | Meaning                                                                 |
| --------- | ----------------------------------------------------------------------- |
| `OK`      | Local content matches upstream byte-for-byte (after rewrite).            |
| `DIFF`    | Local exists but differs — would be overwritten on sync.                 |
| `NEW`     | Upstream has a skill or script not present locally — would be created.   |
| `RETIRED` | Local skill no longer exists upstream. Informational; sync won't delete. |

Default to `--check` when the user asks "are my skills current?" or
"what changed?" — it answers the question without touching anything.

**Sync (destructive).** Pull every upstream skill and overwrite the
local copy. Use when the user explicitly wants to refresh.

```sh
.claude/skills/update-skills/scripts/sync-titan-tyr-skills.sh
```

Either mode:
- discovers every skill under `.claude/skills/<name>/` on `main` via the
  GitHub trees API;
- (sync) writes each `SKILL.md` to `.claude/skills/<name>/SKILL.md`;
- (sync) pulls each skill's own `scripts/` directory wholesale to
  `.claude/skills/<name>/scripts/`;
- (sync) pulls the shared helper bundle from
  `.claude/skills/_shared/scripts/` to the matching local path;
- (sync) marks pulled `.sh` files executable.

All fetches go through `gh api` so the consumer's `gh` auth is the only
credential needed (no token juggling for raw.githubusercontent.com on a
private repo).

Override env vars if needed (rare):

| Variable           | Default                  | Purpose                                          |
| ------------------ | ------------------------ | ------------------------------------------------ |
| `TITAN_TYR_REPO`   | `Westfall-io/titan-tyr`  | Source repo (e.g. for a fork or staging mirror). |
| `TITAN_TYR_BRANCH` | `main`                   | Source branch (usually unchanged).               |

### 3. Report

**Check mode.** The script's own output is the report — pass it through.
If the script exits 0 (`Up to date`), say so. If it exits 1 (`DRIFT
detected`), summarise the DIFF / NEW / RETIRED counts and recommend a
sync. RETIRED entries are informational; ask the user whether to remove
the local-only skill (the sync would not).

**Sync mode.** Tell the user:

- how many skills were synced (the script prints the count);
- if the consumer commits `.claude/skills/` to git, run `git status` /
  `git diff --stat` after and surface adds vs modifies (deletes won't
  show — see below);
- if the consumer doesn't track `.claude/skills/` in git, just report the
  count.

If the consumer's local skill set is *larger* than what was pulled, name
the skills present locally but missing on `main`. They were retired
upstream; the script does not auto-delete (avoids wiping consumer-local
custom skills), so the user decides whether to remove them.

## Notes

- **Self-update is intentional.** Running this skill pulls a fresh copy
  of the skill itself (`update-skills`). The version executing the script
  is whichever was on disk at invocation; the next invocation uses
  whatever just got pulled.
- **Source of truth is `main`, not a release tag.** titan-tyr ships skills
  only after CI passes on `main`; there is no separate release channel
  for the skill catalog.
- **Helper layout mirrors source.** Each skill's own helpers live under
  `.claude/skills/<name>/scripts/`; cross-cutting helpers (the `tyr-*`
  family) live under `.claude/skills/_shared/scripts/`. Source and
  destination paths match, so SKILL bodies reference the same path
  whether you're in titan-tyr or a downstream consumer.
- **Deletion is manual.** A skill removed upstream lingers locally until
  the user removes it. This avoids wiping any custom skills the consumer
  added under `.claude/skills/`.
