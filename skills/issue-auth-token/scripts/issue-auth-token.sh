#!/usr/bin/env bash
# Issue a per-caller auth token via POST /auth-tokens (#81 + #82 + #84).
#
# Reads `TITAN_TYR_TOKEN` from .env in the current directory and uses
# it as the admin bearer for the request. The plaintext of the freshly
# issued token is returned by the API exactly once — this script
# echoes it to stdout (separately from the human-readable summary on
# stderr) so a caller can pipe the last line into a secret store.
#
# Usage:
#   issue-auth-token.sh \
#       --actor <slug> \
#       --description <one-line> \
#       --scopes read,write \
#       [--expires-at 2026-12-31T23:59:59Z]
#
# Environment:
#   TITAN_TYR_URL    required, e.g. http://localhost:18000
#   .env (CWD)       required, must contain TITAN_TYR_TOKEN=<admin-token>

set -euo pipefail

usage() {
  sed -n '2,/^set -euo/p' "$0" | sed 's/^# //; s/^#//'
  exit 2
}

actor=""
description=""
scopes=""
expires_at=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --actor) actor="$2"; shift 2 ;;
    --description) description="$2"; shift 2 ;;
    --scopes) scopes="$2"; shift 2 ;;
    --expires-at) expires_at="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

if [[ -z "$actor" || -z "$description" || -z "$scopes" ]]; then
  echo "missing one of --actor / --description / --scopes" >&2
  usage
fi

if [[ -z "${TITAN_TYR_URL:-}" ]]; then
  echo "TITAN_TYR_URL is not set" >&2
  exit 2
fi

# .env reading. Per the skill spec: bail with explicit instructions
# if .env doesn't exist or doesn't define TITAN_TYR_TOKEN.
if [[ ! -f .env ]]; then
  cat >&2 <<'EOF'
ERROR: .env not found in the current directory.

Create a .env file here that contains a working admin token, then re-run:

    echo 'TITAN_TYR_TOKEN=<your-admin-token-plaintext>' > .env
    chmod 600 .env

Where to get the admin token:
- If this is the first deploy and no tokens exist yet:
      ssh into the API host and run
          python -m src.cli issue-token \
              --actor <your-identity> \
              --description 'admin token' \
              --scopes revoke-agent
      The plaintext is printed exactly once. Paste it into .env.
- If admin tokens exist, ask another admin to issue one for you via
  /issue-auth-token (this same skill, run from their machine).
EOF
  exit 2
fi

# Source .env without exporting anything else into the caller's shell;
# only consume TITAN_TYR_TOKEN. `set -a` would leak unrelated vars.
TITAN_TYR_TOKEN=""
# shellcheck disable=SC1091
TITAN_TYR_TOKEN=$(grep -E '^TITAN_TYR_TOKEN=' .env | head -1 | cut -d= -f2- | tr -d "'\"")

if [[ -z "${TITAN_TYR_TOKEN:-}" ]]; then
  cat >&2 <<'EOF'
ERROR: .env exists but does not define TITAN_TYR_TOKEN.

Add this line to .env, then re-run:

    TITAN_TYR_TOKEN=<your-admin-token-plaintext>

If you don't have an admin token yet, see the instructions printed
when .env is missing entirely (delete .env and re-run for those
instructions, or read the issue-auth-token SKILL.md).
EOF
  exit 2
fi

# Build the JSON payload via python (avoids fragile shell-quoting of
# the description string, which may contain spaces / quotes).
payload=$(python3 - "$actor" "$description" "$scopes" "$expires_at" <<'PYEOF'
import json, sys
actor, description, scopes_csv, expires_at = sys.argv[1:5]
scopes = [s.strip() for s in scopes_csv.split(",") if s.strip()]
body = {"actor": actor, "description": description, "scopes": scopes}
if expires_at:
    body["expires_at"] = expires_at
print(json.dumps(body))
PYEOF
)

response=$(curl -fsS -X POST \
  -H "Authorization: Bearer $TITAN_TYR_TOKEN" \
  -H "Content-Type: application/json" \
  --data "$payload" \
  "${TITAN_TYR_URL%/}/auth-tokens")

# Parse with python so we don't take a jq dependency. Surface the
# human summary on stderr; emit the plaintext token alone on stdout
# (last line) so callers can pipe it.
python3 - <<PYEOF
import json, sys
r = json.loads('''$response''')
print("=" * 60, file=sys.stderr)
print("Auth token issued. SAVE THE PLAINTEXT — it will not be shown", file=sys.stderr)
print("again. The DB only stores the hash + the 8-char prefix.", file=sys.stderr)
print(f"  id:           {r['id']}", file=sys.stderr)
print(f"  actor:        {r['actor']}", file=sys.stderr)
print(f"  description:  {r['description']}", file=sys.stderr)
print(f"  scopes:       {r['scopes']}", file=sys.stderr)
print(f"  issued_at:    {r['issued_at']}", file=sys.stderr)
print(f"  expires_at:   {r.get('expires_at')}", file=sys.stderr)
print(f"  prefix:       {r['token_prefix']}…", file=sys.stderr)
print("=" * 60, file=sys.stderr)
print(r["token"])
PYEOF
