#!/usr/bin/env bash
# Print version + body for a contract by id.
#
# Usage:
#   scripts/show-contract.sh <contract_id>             # version + body
#   scripts/show-contract.sh <contract_id> --meta      # JSON metadata only
#   scripts/show-contract.sh <contract_id> --body      # markdown body only
#   scripts/show-contract.sh <contract_id> --proposals # active version + open proposal versions
#
# Env:
#   TITAN_TYR_URL    default http://localhost:18000  (live stack)
#   TITAN_TYR_TOKEN  default sysmlv2

set -euo pipefail

cid="${1:?usage: show-contract.sh <contract_id> [--meta|--body|--proposals]}"
mode="${2:-default}"
url="${TITAN_TYR_URL:-http://localhost:18000}"
token="${TITAN_TYR_TOKEN:-sysmlv2}"

# --proposals hits a different endpoint and doesn't need the body.
if [[ "$mode" == "--proposals" ]]; then
  curl -fsS -H "Authorization: Bearer $token" \
    "$url/contracts/$cid/proposals" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"contract_id": d.get("contract_id"), "active_version": d.get("active_version"), "open_proposals": [p["version"] for p in d.get("proposals", [])]}, indent=2))'
  exit 0
fi

raw="$(curl -fsS -H "Authorization: Bearer $token" "$url/contracts/$cid")"

case "$mode" in
  --meta)
    printf '%s' "$raw" | python3 -c 'import json,sys; d=json.load(sys.stdin); d.pop("markdown", None); print(json.dumps(d, indent=2))'
    ;;
  --body)
    printf '%s' "$raw" | python3 -c 'import json,sys; print(json.load(sys.stdin)["markdown"])'
    ;;
  default)
    printf '%s' "$raw" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(f"contract_id: {d[\"contract_id\"]}")
print(f"owner:       {d[\"owner\"]}")
print(f"counterparty:{d[\"counterparty\"]}")
print(f"subtype:     {d[\"subtype\"]}{(\"/\" + d[\"connection_type\"]) if d.get(\"connection_type\") else \"\"}")
print(f"version:     {d[\"version\"]}")
print(f"updated_at:  {d[\"updated_at\"]}")
print("---")
print(d["markdown"])
'
    ;;
  *)
    echo "unknown mode: $mode (expected --meta, --body, --proposals, or omit)" >&2
    exit 2
    ;;
esac
