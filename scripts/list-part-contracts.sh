#!/usr/bin/env bash
# Tabular summary of contracts touching a registered part. Reads from
# /parts/{name}/contracts and renders id (truncated), endpoints, subtype,
# connection_type, version, project tag, and created_by_actor.
#
# Usage:
#   scripts/list-part-contracts.sh <part_name>           # human table
#   scripts/list-part-contracts.sh <part_name> --json    # raw JSON
#
# Env:
#   TITAN_TYR_URL    default http://localhost:18000  (live stack)
#   TITAN_TYR_TOKEN  default sysmlv2

set -euo pipefail

name="${1:?usage: list-part-contracts.sh <part_name> [--json]}"
mode="${2:-table}"
url="${TITAN_TYR_URL:-http://localhost:18000}"
token="${TITAN_TYR_TOKEN:-sysmlv2}"

raw="$(curl -fsS -H "Authorization: Bearer $token" "$url/parts/$name/contracts?limit=100")"

case "$mode" in
  --json)
    printf '%s' "$raw" | python3 -m json.tool
    ;;
  table)
    RAW="$raw" python3 - <<'PY'
import json, os
d = json.loads(os.environ['RAW'])
part = d.get('part', '?')
results = d.get('results', [])
if not results:
    print(f'(no contracts touching {part})')
    raise SystemExit(0)
print(f'{"id":<10}  {"owner":<22} {"counterparty":<22} {"subtype/conn":<22} {"ver":<10} {"project":<14} actor')
for r in results:
    cid = r['contract_id'][:8]
    sub = r['subtype']
    ct = r.get('connection_type')
    if ct:
        sub = f'{sub}/{ct}'
    owner = r['owner']
    cp = r['counterparty']
    ver = r['version']
    proj = str(r.get('project'))
    actor = r.get('created_by_actor') or '-'
    print(f'{cid:<10}  {owner:<22} {cp:<22} {sub:<22} {ver:<10} {proj:<14} {actor}')
nxt = d.get('next')
if nxt:
    print(f'\n(more — next cursor: {nxt})')
PY
    ;;
  *)
    echo "unknown mode: $mode (expected --json or omit for table)" >&2
    exit 2
    ;;
esac
