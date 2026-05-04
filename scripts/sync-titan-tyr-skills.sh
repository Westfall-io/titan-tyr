#!/usr/bin/env bash
# Pull or check the titan-tyr skill catalog from
# github.com/Westfall-io/titan-tyr@main against local copies under
# .claude/skills/<name>/.
#
# Usage:
#   sync-titan-tyr-skills.sh             # sync (destructive overwrite)
#   sync-titan-tyr-skills.sh --check     # drift check only (no writes)
#
# Each pulled skill is namespaced so it doesn't collide with the consumer's
# top-level scripts/ dir:
#   - the skill body lands at .claude/skills/<name>/SKILL.md
#   - every scripts/<x>.sh referenced by the body is captured at
#     .claude/skills/<name>/scripts/<x>.sh
#   - the body is rewritten so its references point at the namespaced copies
#
# In sync mode: destructive on the consumer side. Local edits to any pulled
# file are overwritten. titan-tyr@main is the source of truth — file
# feedback as a titan-tyr issue, not by hand-editing the local copy.
#
# In --check mode: read-only. SHA-compares each upstream SKILL.md (after
# applying the namespace rewrite) and each referenced script against the
# local copy. Prints `OK` / `DIFF` / `NEW` / `RETIRED` per file. Exits 1
# if any DIFF or NEW (i.e. a real sync would change something); RETIRED
# entries are informational (sync doesn't auto-delete).
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

command -v gh      >/dev/null || { echo "gh CLI required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 required (used for path rewrite)" >&2; exit 1; }
command -v git     >/dev/null || { echo "git required (used for hash-object)" >&2; exit 1; }

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

# Rewrite scripts/X.sh -> <dest>/scripts/X.sh on stdin, write to stdout.
# Anchor with (^|[^/]) so paths already prefixed are left alone (idempotent).
rewrite_skill_body() {
  DEST="$1" python3 -c '
import os, re, sys
dest = os.environ["DEST"]
sys.stdout.write(re.sub(
    r"(^|[^/])scripts/([A-Za-z0-9_-]+\.sh)",
    lambda m: f"{m.group(1)}{dest}/scripts/{m.group(2)}",
    sys.stdin.read(),
    flags=re.MULTILINE,
))
'
}

mkdir -p "$skills_dir"

echo "Discovering skills on $repo@$branch ..."
skills=()
while IFS= read -r line; do
  skills+=("$line")
done < <(
  gh api "repos/$repo/git/trees/$branch?recursive=1" \
    --jq '.tree[] | select(.type == "blob" and (.path | startswith(".claude/skills/")) and (.path | endswith("/SKILL.md"))) | .path | sub("^\\.claude/skills/"; "") | sub("/SKILL\\.md$"; "")'
)

if (( ${#skills[@]} == 0 )); then
  echo "no skills found on $repo@$branch — aborting" >&2
  exit 1
fi

echo "  ${#skills[@]} skills found"
echo

drift=0

for name in "${skills[@]}"; do
  dest="$skills_dir/$name"

  if [[ "$mode" == "check" ]]; then
    if [[ ! -f "$dest/SKILL.md" ]]; then
      printf "NEW     %s\n" "$name"
      drift=1
      continue
    fi

    upstream_hash="$(
      gh api -H "Accept: application/vnd.github.raw" \
        "repos/$repo/contents/.claude/skills/$name/SKILL.md?ref=$branch" \
      | rewrite_skill_body "$dest" \
      | git hash-object --stdin
    )"
    local_hash="$(git hash-object "$dest/SKILL.md")"
    if [[ "$upstream_hash" == "$local_hash" ]]; then
      printf "OK      %s/SKILL.md\n" "$name"
    else
      printf "DIFF    %s/SKILL.md\n" "$name"
      drift=1
    fi

    # Compare each script referenced by the upstream body. The upstream body
    # has bare scripts/X.sh; the local copy has .claude/skills/<name>/scripts/X.sh.
    refs="$(
      gh api -H "Accept: application/vnd.github.raw" \
        "repos/$repo/contents/.claude/skills/$name/SKILL.md?ref=$branch" \
      | grep -Eho 'scripts/[A-Za-z0-9_-]+\.sh' | sort -u || true
    )"
    if [[ -n "$refs" ]]; then
      while IFS= read -r ref; do
        [[ -z "$ref" ]] && continue
        upstream_sh_hash="$(
          gh api -H "Accept: application/vnd.github.raw" \
            "repos/$repo/contents/$ref?ref=$branch" \
          | git hash-object --stdin
        )"
        if [[ -f "$dest/$ref" ]]; then
          local_sh_hash="$(git hash-object "$dest/$ref")"
          if [[ "$upstream_sh_hash" == "$local_sh_hash" ]]; then
            printf "OK      %s/%s\n" "$name" "$ref"
          else
            printf "DIFF    %s/%s\n" "$name" "$ref"
            drift=1
          fi
        else
          printf "NEW     %s/%s\n" "$name" "$ref"
          drift=1
        fi
      done <<< "$refs"
    fi
    continue
  fi

  # sync mode
  mkdir -p "$dest"
  gh api -H "Accept: application/vnd.github.raw" \
    "repos/$repo/contents/.claude/skills/$name/SKILL.md?ref=$branch" \
    > "$dest/SKILL.md"
  refs="$(grep -Eho 'scripts/[A-Za-z0-9_-]+\.sh' "$dest/SKILL.md" | sort -u || true)"
  if [[ -n "$refs" ]]; then
    mkdir -p "$dest/scripts"
    while IFS= read -r ref; do
      [[ -z "$ref" ]] && continue
      gh api -H "Accept: application/vnd.github.raw" \
        "repos/$repo/contents/$ref?ref=$branch" \
        > "$dest/$ref"
      chmod +x "$dest/$ref"
    done <<< "$refs"
    rewrite_skill_body "$dest" < "$dest/SKILL.md" > "$dest/SKILL.md.tmp"
    mv "$dest/SKILL.md.tmp" "$dest/SKILL.md"
  fi
  echo "  pulled: $name"
done

if [[ "$mode" == "check" ]]; then
  # Also surface local skills not on upstream — informational, doesn't fail.
  for local_dir in "$skills_dir"/*/; do
    [[ -d "$local_dir" ]] || continue
    local_name="$(basename "$local_dir")"
    found=0
    for up_name in "${skills[@]}"; do
      if [[ "$up_name" == "$local_name" ]]; then found=1; break; fi
    done
    if (( !found )); then
      printf "RETIRED %s (local only — removed upstream)\n" "$local_name"
    fi
  done

  echo
  if (( drift )); then
    echo "DRIFT detected. Run without --check to overwrite local with upstream."
    exit 1
  else
    echo "Up to date with $repo@$branch."
  fi
else
  echo
  echo "Done. ${#skills[@]} skills synced from $repo@$branch into $skills_dir/."
  echo "Note: this script does not delete local skills missing from main —"
  echo "if a skill was retired upstream, remove it manually."
fi
