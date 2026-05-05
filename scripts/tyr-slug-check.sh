#!/usr/bin/env bash
# Slug pre-flight: is this part name free? (#63)
#
# Usage:
#   tyr-slug-check <slug>
#
# Behavior:
#   - GET /parts/{slug}.
#   - 404 → prints "free", exits 0.
#   - 200 → prints "taken: <subtype> part `<name>`, registered <date>
#           by <actor>, project=<slug-or-none>", exits 1.
#   - any other status → prints the body to stderr, exits curl's
#     exit code.
#
# The exit-code semantics are inverted from a raw curl: free = 0,
# taken = 1, so the script is composable with shell `if`:
#
#   if scripts/tyr-slug-check.sh foo; then
#     echo "registering foo..."
#   fi
#
# Env: TITAN_TYR_URL (required), TITAN_TYR_TOKEN (default sysmlv2).

set -euo pipefail

slug="${1:?usage: tyr-slug-check <slug>}"

if [[ -z "${TITAN_TYR_URL:-}" ]]; then
  echo "TITAN_TYR_URL is not set" >&2
  exit 2
fi
url="${TITAN_TYR_URL%/}"
token="${TITAN_TYR_TOKEN:-sysmlv2}"

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

# -w writes the status code to stdout; we redirect that into the
# variable. -o sends body to the temp file. --fail-with-body keeps
# the body even on 4xx.
status=$(curl -sS -o "$tmp" -w '%{http_code}' \
  -H "Authorization: Bearer $token" \
  "$url/parts/$slug")

case "$status" in
  200)
    # Script source via env var because stdin is the JSON file —
    # using a heredoc would conflict with the `<` redirect.
    BODY="$(cat "$tmp")" SLUG="$slug" python3 -c '
import json, os
d = json.loads(os.environ["BODY"])
slug = os.environ["SLUG"]
subtype = d.get("subtype", "?")
created_by = d.get("created_by_actor") or "(no actor recorded)"
project = d.get("project") or "(none)"
updated = (d.get("updated_at") or "?")[:10]
print(
    f"taken: {subtype} part `{slug}`, "
    f"updated {updated} by {created_by}, project={project}"
)
'
    exit 1
    ;;
  404)
    echo "free"
    exit 0
    ;;
  *)
    echo "unexpected status $status" >&2
    cat "$tmp" >&2
    exit 2
    ;;
esac
