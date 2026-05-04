#!/usr/bin/env bash
# Propose a new version of a template.
#
# Usage:
#   scripts/propose-template.sh <kind> <md-file> <version>
#
# Reads the markdown body from <md-file> and POSTs to
# /templates/{kind}/proposals with X-Actor: titan-tyr (the agent identity;
# the human accepts under their own X-Actor per the two-party rule).
#
# Env:
#   TITAN_TYR_URL    default http://localhost:18000  (live stack)
#   TITAN_TYR_TOKEN  default sysmlv2
#   TITAN_TYR_ACTOR  default titan-tyr

set -euo pipefail

kind="${1:?usage: propose-template.sh <kind> <md-file> <version>}"
mdfile="${2:?usage: propose-template.sh <kind> <md-file> <version>}"
version="${3:?usage: propose-template.sh <kind> <md-file> <version>}"
url="${TITAN_TYR_URL:-http://localhost:18000}"
token="${TITAN_TYR_TOKEN:-sysmlv2}"
actor="${TITAN_TYR_ACTOR:-titan-tyr}"

[[ -f "$mdfile" ]] || { echo "no such file: $mdfile" >&2; exit 1; }

payload="$(MD="$mdfile" V="$version" python3 -c '
import json, os
print(json.dumps({"version": os.environ["V"], "markdown": open(os.environ["MD"]).read()}))
')"

curl -fsS -X POST \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  -H "X-Actor: $actor" \
  --data "$payload" \
  "$url/templates/$kind/proposals" \
  | python3 -m json.tool
