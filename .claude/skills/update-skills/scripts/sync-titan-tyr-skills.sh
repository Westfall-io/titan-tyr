#!/usr/bin/env bash
# Pull or check the titan-tyr skill catalog from
# github.com/Westfall-io/titan-tyr@main against local copies under
# .claude/skills/.
#
# Usage:
#   sync-titan-tyr-skills.sh             # sync (destructive overwrite)
#   sync-titan-tyr-skills.sh --check     # drift check only (no writes)
#
# Layout (source and destination match — no path rewriting):
#   .claude/skills/<name>/SKILL.md
#   .claude/skills/<name>/scripts/<x>.sh   (per-skill helpers, if any)
#   .claude/skills/_shared/scripts/<x>.sh  (cross-cutting helpers)
#
# In sync mode: destructive on the consumer side. Local edits to any
# pulled file are overwritten. titan-tyr@main is the source of truth
# — file feedback as a titan-tyr issue, not by hand-editing the
# local copy.
#
# In --check mode: read-only. Hash-compares each upstream file against
# the local copy. Prints `OK` / `DIFF` / `NEW` / `RETIRED` per file.
# Exits 1 if any DIFF or NEW (i.e. a real sync would change something);
# RETIRED entries are informational (sync doesn't auto-delete).
#
# All fetches go through `gh api` so private repos work without juggling
# raw.githubusercontent.com tokens.
#
# Env:
#   TITAN_TYR_REPO    default Westfall-io/titan-tyr
#   TITAN_TYR_BRANCH  default main

set -euo pipefail

mode="sync"
case "${1:-}" in
  "")              ;;
  --check)         mode="check" ;;
  -h|--help)
    sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
    exit 0
    ;;
  *)
    echo "unknown arg: ${1} (expected --check or omit)" >&2
    exit 2
    ;;
esac

repo="${TITAN_TYR_REPO:-Westfall-io/titan-tyr}"
branch="${TITAN_TYR_BRANCH:-main}"
skills_dir=".claude/skills"

command -v gh  >/dev/null || { echo "gh CLI required" >&2; exit 1; }
command -v git >/dev/null || { echo "git required (used for hash-object)" >&2; exit 1; }

# Refuse to run inside titan-tyr itself — the canonical source lives here.
if origin="$(git remote get-url origin 2>/dev/null)"; then
  case "$origin" in
    *"$repo"*|*"${repo%.git}".git*)
      echo "refusing to run: this repo IS $repo (the source of truth)." >&2
      echo "edit skills here directly. set TITAN_TYR_REPO to override." >&2
      exit 2
      ;;
  esac
fi

mkdir -p "$skills_dir"

echo "Discovering skills + shared helpers on $repo@$branch ..."

# Every blob under .claude/skills/. Includes SKILL.md files and any
# .sh under <skill>/scripts/ or _shared/scripts/. bash 3.2 compatible
# (no mapfile).
paths=()
while IFS= read -r line; do
  paths+=("$line")
done < <(
  gh api "repos/$repo/git/trees/$branch?recursive=1" \
    --jq '.tree[]
          | select(.type == "blob" and (.path | startswith(".claude/skills/")))
          | .path'
)

if (( ${#paths[@]} == 0 )); then
  echo "no skill files found on $repo@$branch — aborting" >&2
  exit 1
fi

skill_count=0
for p in "${paths[@]}"; do
  case "$p" in
    .claude/skills/*/SKILL.md) skill_count=$((skill_count+1)) ;;
  esac
done
echo "  $skill_count SKILL.md files, $(( ${#paths[@]} - skill_count )) helper files"
echo

drift=0

fetch_raw() {
  gh api -H "Accept: application/vnd.github.raw" \
    "repos/$repo/contents/$1?ref=$branch"
}

for path in "${paths[@]}"; do
  if [[ "$mode" == "check" ]]; then
    if [[ ! -f "$path" ]]; then
      printf "NEW     %s\n" "$path"
      drift=1
      continue
    fi
    upstream_hash="$(fetch_raw "$path" | git hash-object --stdin)"
    local_hash="$(git hash-object "$path")"
    if [[ "$upstream_hash" == "$local_hash" ]]; then
      printf "OK      %s\n" "$path"
    else
      printf "DIFF    %s\n" "$path"
      drift=1
    fi
  else
    mkdir -p "$(dirname "$path")"
    fetch_raw "$path" > "$path"
    case "$path" in
      *.sh) chmod +x "$path" ;;
    esac
    echo "  pulled: $path"
  fi
done

if [[ "$mode" == "check" ]]; then
  # Surface RETIRED entries: local files that aren't on upstream.
  while IFS= read -r local_path; do
    found=0
    for p in "${paths[@]}"; do
      [[ "$p" == "$local_path" ]] && { found=1; break; }
    done
    if (( ! found )); then
      printf "RETIRED %s\n" "$local_path"
    fi
  done < <(
    find "$skills_dir" -type f \( -name 'SKILL.md' -o -name '*.sh' \) \
      | sort
  )
  echo
  if (( drift )); then
    echo "DRIFT detected — re-run without --check to sync."
    exit 1
  fi
  echo "Up to date."
  exit 0
fi
