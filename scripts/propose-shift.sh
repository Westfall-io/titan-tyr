#!/usr/bin/env bash
# POST a pre-built JSON body to a shift-proposal endpoint, with bearer + X-Actor.
#
# Usage:
#   scripts/propose-shift.sh <path> <json-file>
#
# Examples:
#   scripts/propose-shift.sh contracts/abc-123/subtype-proposals    .scratch/shift.json
#   scripts/propose-shift.sh contracts/abc-123/endpoint-proposals   .scratch/shift.json
#   scripts/propose-shift.sh parts/payments/name-proposals          .scratch/shift.json
#   scripts/propose-shift.sh parts/payments/subtype-proposals       .scratch/shift.json
#
# Each shift type has its own required body shape (subtype shifts carry
# `subtype` + optional `connection_type`; name shifts carry `new_name`; etc.)
# so the calling skill builds the JSON and this script only handles the POST
# boilerplate.
#
# Env:
#   TITAN_TYR_URL    default http://localhost:18000  (live stack)
#   TITAN_TYR_TOKEN  default sysmlv2
#   TITAN_TYR_ACTOR  default titan-tyr

set -euo pipefail

path="${1:?usage: propose-shift.sh <path> <json-file>}"
jsonfile="${2:?usage: propose-shift.sh <path> <json-file>}"
url="${TITAN_TYR_URL:-http://localhost:18000}"
token="${TITAN_TYR_TOKEN:-sysmlv2}"
actor="${TITAN_TYR_ACTOR:-titan-tyr}"

[[ -f "$jsonfile" ]] || { echo "no such file: $jsonfile" >&2; exit 1; }

curl -fsS -X POST \
  -H "Authorization: Bearer $token" \
  -H "Content-Type: application/json" \
  -H "X-Actor: $actor" \
  --data @"$jsonfile" \
  "$url/$path" \
  | python3 -m json.tool
