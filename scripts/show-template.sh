#!/usr/bin/env bash
# Print active version + body for a template kind.
#
# Usage:
#   scripts/show-template.sh <kind>          # body to stdout
#   scripts/show-template.sh <kind> --meta   # JSON metadata (version etc) only
#
# Env:
#   TITAN_TYR_URL    default http://localhost:18000  (live stack)
#   TITAN_TYR_TOKEN  default sysmlv2

set -euo pipefail

kind="${1:?usage: show-template.sh <kind> [--meta]}"
mode="${2:-body}"
url="${TITAN_TYR_URL:-http://localhost:18000}"
token="${TITAN_TYR_TOKEN:-sysmlv2}"

case "$mode" in
  body)
    curl -fsS -H "Authorization: Bearer $token" -H "Accept: text/markdown" \
      "$url/templates/$kind"
    ;;
  --meta)
    # /templates/{kind}/proposals carries the active version inline.
    curl -fsS -H "Authorization: Bearer $token" \
      "$url/templates/$kind/proposals" \
      | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"kind": d.get("kind"), "active_version": d.get("active_version"), "open_proposals": [p["version"] for p in d.get("proposals", [])]}, indent=2))'
    ;;
  *)
    echo "unknown mode: $mode (expected --meta or omit for body)" >&2
    exit 2
    ;;
esac
