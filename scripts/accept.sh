#!/usr/bin/env bash
# POST /<path>/accept with bearer + X-Actor. No request body.
#
# Usage:
#   scripts/accept.sh <path> [--single-operator]
#
# Examples:
#   scripts/accept.sh templates/software/proposals/2.6.0
#   scripts/accept.sh contracts/abc-123/proposals/2.6.0 --single-operator
#   scripts/accept.sh contracts/abc-123/subtype-proposals/uuid-here
#   scripts/accept.sh contracts/abc-123/endpoint-proposals/uuid-here
#   scripts/accept.sh parts/payments/name-proposals/uuid-here
#   scripts/accept.sh parts/payments/subtype-proposals/uuid-here
#
# The script appends `/accept` (and `?single_operator=true` when the flag
# is present) so callers pass the resource path, not the action.
#
# Env:
#   TITAN_TYR_URL    default http://localhost:18000  (live stack)
#   TITAN_TYR_TOKEN  default sysmlv2
#   TITAN_TYR_ACTOR  default titan-tyr
#
# The X-Actor header is the acceptor identity for the proposer-doesn't-accept
# rule (provider v0.16.0+). If the caller proposed the same record, the API
# returns 409 unless `--single-operator` is used.

set -euo pipefail

path="${1:?usage: accept.sh <path> [--single-operator]}"
flag="${2:-}"
url="${TITAN_TYR_URL:-http://localhost:18000}"
token="${TITAN_TYR_TOKEN:-sysmlv2}"
actor="${TITAN_TYR_ACTOR:-titan-tyr}"

suffix="/accept"
case "$flag" in
  "")                ;;
  --single-operator) suffix="/accept?single_operator=true" ;;
  *) echo "unknown flag: $flag (expected --single-operator or omit)" >&2; exit 2 ;;
esac

curl -fsS -X POST \
  -H "Authorization: Bearer $token" \
  -H "X-Actor: $actor" \
  "$url/$path$suffix" \
  | python3 -m json.tool
