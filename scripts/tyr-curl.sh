#!/usr/bin/env bash
# Header-injecting curl wrapper for the titan-tyr API (#63).
#
# Reads TITAN_TYR_URL / TITAN_TYR_TOKEN / TITAN_TYR_ACTOR from env and
# adds Authorization, X-Actor, and (for write methods) Content-Type so
# every example in every SKILL doesn't have to re-type them.
#
# Usage:
#   tyr-curl <METHOD> <PATH> [extra curl args]
#
# Examples:
#   tyr-curl GET /parts
#   tyr-curl GET /parts/foo
#   tyr-curl POST /parts --data @.scratch/foo.json
#   tyr-curl PUT /contracts/abc --data '{"project":"watchervault"}'
#
# Behavior:
#   - <PATH> is appended to $TITAN_TYR_URL. Pass either /parts or
#     parts; both work.
#   - Authorization: Bearer $TITAN_TYR_TOKEN (default sysmlv2).
#   - X-Actor: $TITAN_TYR_ACTOR (omitted if unset; warns on stderr
#     for write methods so the missing paper trail is visible).
#   - Content-Type: application/json on POST/PUT/PATCH (suppressed
#     if you pass your own -H Content-Type).
#   - Pretty-prints JSON responses by default; --raw passes the body
#     through unchanged (useful for piping to jq or to a file).
#   - Always uses curl -fsS so HTTP failures exit non-zero with the
#     response body on stderr.
#
# Exit codes:
#   curl's exit code on failure; 0 on success.

set -euo pipefail

if [[ $# -lt 2 ]]; then
  sed -n '2,/^set -euo/p' "$0" | sed 's/^# //; s/^#//'
  exit 2
fi

method="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
path="$2"
shift 2

if [[ -z "${TITAN_TYR_URL:-}" ]]; then
  echo "TITAN_TYR_URL is not set" >&2
  exit 2
fi

raw=0
extra=()
for arg in "$@"; do
  case "$arg" in
    --raw) raw=1 ;;
    *) extra+=("$arg") ;;
  esac
done

url="${TITAN_TYR_URL%/}"
case "$path" in
  /*) full="$url$path" ;;
  *)  full="$url/$path" ;;
esac

token="${TITAN_TYR_TOKEN:-sysmlv2}"
actor="${TITAN_TYR_ACTOR:-}"

headers=(-H "Authorization: Bearer $token")
if [[ -n "$actor" ]]; then
  headers+=(-H "X-Actor: $actor")
elif [[ "$method" =~ ^(POST|PUT|PATCH|DELETE)$ ]]; then
  echo "warning: TITAN_TYR_ACTOR is unset — paper trail on this $method will be null" >&2
fi

# Add Content-Type unless caller already supplied one or method has no body.
caller_has_ct=0
for arg in "${extra[@]+"${extra[@]+"${extra[@]}"}"}"; do
  lc=$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')
  case "$lc" in
    *content-type*) caller_has_ct=1 ;;
  esac
done
if [[ "$method" =~ ^(POST|PUT|PATCH)$ && $caller_has_ct -eq 0 ]]; then
  headers+=(-H "Content-Type: application/json")
fi

if (( raw )); then
  exec curl -fsS -X "$method" "${headers[@]}" "${extra[@]+"${extra[@]}"}" "$full"
fi

# Capture body, pretty-print if it parses as JSON, otherwise stream
# verbatim. Preserve curl's exit code so failures still surface.
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
if curl -fsS -X "$method" "${headers[@]}" "${extra[@]+"${extra[@]}"}" "$full" -o "$tmp"; then
  if python3 -m json.tool < "$tmp" 2>/dev/null; then
    :
  else
    cat "$tmp"
  fi
else
  rc=$?
  cat "$tmp" >&2 || true
  exit "$rc"
fi
