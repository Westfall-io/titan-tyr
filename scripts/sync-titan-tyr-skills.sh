#!/usr/bin/env bash
# Pull the titan-tyr skill catalog from github.com/Westfall-io/titan-tyr@main
# and overwrite local copies under .claude/skills/<name>/.
#
# Each pulled skill is namespaced so it doesn't collide with the consumer's
# top-level scripts/ dir:
#   - the skill body lands at .claude/skills/<name>/SKILL.md
#   - every scripts/<x>.sh referenced by the body is captured at
#     .claude/skills/<name>/scripts/<x>.sh
#   - the body is rewritten so its references point at the namespaced copies
#
# This is destructive on the consumer side. Local edits to any pulled file
# are overwritten. titan-tyr@main is the source of truth — file feedback as
# a titan-tyr issue, not by hand-editing the local copy.
#
# All fetches go through `gh api` so private repos work without juggling
# raw.githubusercontent.com tokens.
#
# Usage:
#   .claude/skills/update-skills/scripts/sync-titan-tyr-skills.sh
#
# Env:
#   TITAN_TYR_REPO    default Westfall-io/titan-tyr
#   TITAN_TYR_BRANCH  default main

set -euo pipefail

repo="${TITAN_TYR_REPO:-Westfall-io/titan-tyr}"
branch="${TITAN_TYR_BRANCH:-main}"
skills_dir=".claude/skills"

command -v gh      >/dev/null || { echo "gh CLI required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 required (used for path rewrite)" >&2; exit 1; }

# Refuse to run inside titan-tyr itself — the canonical source lives here.
if origin="$(git remote get-url origin 2>/dev/null)"; then
  case "$origin" in
    *"$repo"*|*"${repo%.git}".git*)
      echo "refusing to sync: this repo IS $repo (the source of truth)." >&2
      echo "edit skills here directly. set TITAN_TYR_REPO to override." >&2
      exit 2
      ;;
  esac
fi

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

for name in "${skills[@]}"; do
  dest="$skills_dir/$name"
  mkdir -p "$dest"
  gh api -H "Accept: application/vnd.github.raw" \
    "repos/$repo/contents/.claude/skills/$name/SKILL.md?ref=$branch" \
    > "$dest/SKILL.md"

  # Find every scripts/<X>.sh reference in the body; pull each into <dest>/scripts/.
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

    # Rewrite scripts/X.sh → <dest>/scripts/X.sh in the body. Anchor with
    # (^|[^/]) so paths already prefixed (e.g. another skill's namespace
    # appearing literally in prose) are left alone.
    DEST="$dest" python3 - "$dest/SKILL.md" <<'PY'
import os, re, sys
p = sys.argv[1]
dest = os.environ["DEST"]
with open(p) as f:
    src = f.read()
new = re.sub(
    r'(^|[^/])scripts/([A-Za-z0-9_-]+\.sh)',
    lambda m: f"{m.group(1)}{dest}/scripts/{m.group(2)}",
    src,
    flags=re.MULTILINE,
)
with open(p, "w") as f:
    f.write(new)
PY
  fi
  echo "  pulled: $name"
done

echo
echo "Done. ${#skills[@]} skills synced from $repo@$branch into $skills_dir/."
echo "Note: this script does not delete local skills missing from main —"
echo "if a skill was retired upstream, remove it manually."
