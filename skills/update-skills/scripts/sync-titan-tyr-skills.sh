#!/usr/bin/env bash
# Pull or check the titan-tyr skill catalog from
# github.com/Westfall-io/titan-tyr@main against local copies under
# .claude/skills/.
#
# Usage:
#   sync-titan-tyr-skills.sh             # sync (destructive overwrite)
#   sync-titan-tyr-skills.sh --check     # drift check only (no writes)
#
# Source / destination layouts (now bifurcated as of titan-tyr v0.34 +
# plugin packaging; #109):
#   upstream source:        skills/<name>/SKILL.md
#                           skills/<name>/scripts/<x>.sh
#                           skills/_shared/scripts/<x>.sh
#   consumer destination:   .claude/skills/<name>/SKILL.md
#                           .claude/skills/<name>/scripts/<x>.sh
#                           .claude/skills/_shared/scripts/<x>.sh
#
# The script rewrites paths from source → destination on pull. The
# destination layout (`.claude/skills/`) is what Claude Code's loader
# expects on the consumer side, so this preserves backwards
# compatibility for consumers that haven't migrated to plugin install.
#
# **Deprecation note:** the preferred way to install the titan-tyr
# skill catalog into a fresh Claude Code session is now the plugin
# marketplace, not this script:
#
#     /plugin marketplace add Westfall-io/titan-tyr
#     /plugin install titan-tyr
#
# Plugin install gives namespacing (`/titan-tyr:register-part`),
# versioning (`#skills-vX.Y.Z` ref pinning), and non-destructive
# `/plugin update`. This script remains for legacy installers and
# drift-check workflows; it will be removed once all known consumers
# have migrated.
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
# Bifurcated source/destination layouts (#109). See header.
source_prefix="skills"
dest_prefix=".claude/skills"

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

mkdir -p "$dest_prefix"

echo "Discovering skills + shared helpers on $repo@$branch under $source_prefix/ ..."

# Every blob under skills/. Includes SKILL.md files and any
# .sh under <skill>/scripts/ or _shared/scripts/. bash 3.2 compatible
# (no mapfile).
src_paths=()
while IFS= read -r line; do
  src_paths+=("$line")
done < <(
  gh api "repos/$repo/git/trees/$branch?recursive=1" \
    --jq ".tree[]
          | select(.type == \"blob\" and (.path | startswith(\"${source_prefix}/\")))
          | .path"
)

if (( ${#src_paths[@]} == 0 )); then
  echo "no skill files found on $repo@$branch under $source_prefix/ — aborting" >&2
  exit 1
fi

# Rewrite source path → destination path (one helper).
to_dest() {
  local src="$1"
  echo "${dest_prefix}/${src#${source_prefix}/}"
}

skill_count=0
for p in "${src_paths[@]}"; do
  case "$p" in
    "${source_prefix}"/*/SKILL.md) skill_count=$((skill_count+1)) ;;
  esac
done
echo "  $skill_count SKILL.md files, $(( ${#src_paths[@]} - skill_count )) helper files"
echo

drift=0

fetch_raw() {
  gh api -H "Accept: application/vnd.github.raw" \
    "repos/$repo/contents/$1?ref=$branch"
}

for src_path in "${src_paths[@]}"; do
  dest_path="$(to_dest "$src_path")"
  if [[ "$mode" == "check" ]]; then
    if [[ ! -f "$dest_path" ]]; then
      printf "NEW     %s\n" "$dest_path"
      drift=1
      continue
    fi
    upstream_hash="$(fetch_raw "$src_path" | git hash-object --stdin)"
    local_hash="$(git hash-object "$dest_path")"
    if [[ "$upstream_hash" == "$local_hash" ]]; then
      printf "OK      %s\n" "$dest_path"
    else
      printf "DIFF    %s\n" "$dest_path"
      drift=1
    fi
  else
    mkdir -p "$(dirname "$dest_path")"
    fetch_raw "$src_path" > "$dest_path"
    case "$dest_path" in
      *.sh) chmod +x "$dest_path" ;;
    esac
    echo "  pulled: $src_path → $dest_path"
  fi
done

if [[ "$mode" == "check" ]]; then
  # Surface RETIRED entries: local files that aren't on upstream.
  while IFS= read -r local_path; do
    # Map local back to expected src path for comparison.
    expected_src="${source_prefix}/${local_path#${dest_prefix}/}"
    found=0
    for p in "${src_paths[@]}"; do
      [[ "$p" == "$expected_src" ]] && { found=1; break; }
    done
    if (( ! found )); then
      printf "RETIRED %s\n" "$local_path"
    fi
  done < <(
    find "$dest_prefix" -type f \( -name 'SKILL.md' -o -name '*.sh' \) \
      | sort
  )
  echo
  if (( drift )); then
    echo "drift detected; rerun without --check to sync."
    exit 1
  else
    echo "in sync (only RETIRED entries above, if any)."
  fi
else
  echo
  echo "sync complete."
  echo
  echo "Reminder: the preferred install path going forward is the"
  echo "plugin marketplace, not this script. To migrate:"
  echo "  /plugin marketplace add ${repo}"
  echo "  /plugin install watchervault"
fi
