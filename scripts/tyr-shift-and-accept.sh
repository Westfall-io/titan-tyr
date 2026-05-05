#!/usr/bin/env bash
# Propose-then-accept loop for solo workflows (#63).
#
# Folds the two-call dance (POST proposal → capture id → POST accept)
# into one command. Designed for documented solo setups where the
# operator is the only party — `--single-operator` is REQUIRED so the
# two-party rule bypass stays visible at the call site.
#
# Subcommands:
#   name-shift             --part NAME --new-name NAME --rationale TEXT
#                          [--rationale-file FILE]
#   part-subtype-shift     --part NAME --new-subtype S --rationale TEXT
#                          [--rationale-file FILE]
#   contract-subtype-shift --contract ID --new-subtype S
#                          [--new-connection-type LABEL]
#                          --rationale TEXT [--rationale-file FILE]
#   endpoint-shift         --contract ID --new-owner OWNER
#                          --new-counterparty CP
#                          --rationale TEXT [--rationale-file FILE]
#   body-bump              --contract ID --version V --md FILE
#
# All five subcommands require `--single-operator` to land the
# accept; without it the helper stops after the propose and prints
# the proposal_id (or version for body-bump) for the second party
# to pick up via the regular accept endpoint.
#
# Env: TITAN_TYR_URL (required), TITAN_TYR_TOKEN, TITAN_TYR_ACTOR.
#
# Aborts cleanly on any 4xx between propose and accept; the
# stranded proposal stays open for manual cleanup or re-accept.

set -euo pipefail

if [[ $# -lt 1 || "$1" == "-h" || "$1" == "--help" ]]; then
  sed -n '2,/^set -euo/p' "$0" | sed 's/^# //; s/^#//'
  exit 2
fi

cmd="$1"
shift

part=""
contract=""
new_name=""
new_subtype=""
new_connection_type=""
new_owner=""
new_counterparty=""
rationale=""
rationale_file=""
version=""
md=""
single_operator=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --part) part="$2"; shift 2 ;;
    --contract) contract="$2"; shift 2 ;;
    --new-name) new_name="$2"; shift 2 ;;
    --new-subtype) new_subtype="$2"; shift 2 ;;
    --new-connection-type) new_connection_type="$2"; shift 2 ;;
    --new-owner) new_owner="$2"; shift 2 ;;
    --new-counterparty) new_counterparty="$2"; shift 2 ;;
    --rationale) rationale="$2"; shift 2 ;;
    --rationale-file) rationale_file="$2"; shift 2 ;;
    --version) version="$2"; shift 2 ;;
    --md) md="$2"; shift 2 ;;
    --single-operator) single_operator=1; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed 's/^# //; s/^#//'; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "${TITAN_TYR_URL:-}" ]]; then
  echo "TITAN_TYR_URL is not set" >&2
  exit 2
fi

if [[ -n "$rationale_file" ]]; then
  if [[ -n "$rationale" ]]; then
    echo "pass either --rationale or --rationale-file, not both" >&2
    exit 2
  fi
  rationale="$(cat "$rationale_file")"
fi

CMD="$cmd" PART="$part" CONTRACT="$contract" \
NEW_NAME="$new_name" NEW_SUBTYPE="$new_subtype" \
NEW_CONNECTION_TYPE="$new_connection_type" \
NEW_OWNER="$new_owner" NEW_COUNTERPARTY="$new_counterparty" \
RATIONALE="$rationale" VERSION="$version" MD="$md" \
SINGLE_OPERATOR="$single_operator" \
URL="${TITAN_TYR_URL%/}" TOKEN="${TITAN_TYR_TOKEN:-sysmlv2}" \
ACTOR="${TITAN_TYR_ACTOR:-}" \
python3 - <<'PY'
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

CMD = os.environ["CMD"]
URL = os.environ["URL"]
TOKEN = os.environ["TOKEN"]
ACTOR = os.environ["ACTOR"]
SINGLE_OPERATOR = os.environ["SINGLE_OPERATOR"] == "1"


def http(method, path, body=None):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if ACTOR:
        headers["X-Actor"] = ACTOR
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{URL}{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def must(env, flag):
    v = os.environ[env]
    if not v:
        sys.exit(f"--{flag} is required for {CMD}")
    return v


# Map subcommand → (propose_path, propose_body, accept_path_template,
# id_field). The id_field key in the propose response provides the
# value for {ID} in the accept template; it's "proposal_id" for the
# four shift kinds and "version" for body-bump.
if CMD == "name-shift":
    part = must("PART", "part")
    propose_path = f"/parts/{part}/name-proposals"
    propose_body = {
        "new_name": must("NEW_NAME", "new-name"),
        "rationale": must("RATIONALE", "rationale (or --rationale-file)"),
    }
    accept_template = f"/parts/{part}/name-proposals/{{id}}/accept"
    id_field = "proposal_id"

elif CMD == "part-subtype-shift":
    part = must("PART", "part")
    propose_path = f"/parts/{part}/subtype-proposals"
    propose_body = {
        "new_subtype": must("NEW_SUBTYPE", "new-subtype"),
        "rationale": must("RATIONALE", "rationale (or --rationale-file)"),
    }
    accept_template = f"/parts/{part}/subtype-proposals/{{id}}/accept"
    id_field = "proposal_id"

elif CMD == "contract-subtype-shift":
    cid = must("CONTRACT", "contract")
    propose_body = {
        "new_subtype": must("NEW_SUBTYPE", "new-subtype"),
        "rationale": must("RATIONALE", "rationale (or --rationale-file)"),
    }
    if os.environ["NEW_CONNECTION_TYPE"]:
        propose_body["new_connection_type"] = os.environ["NEW_CONNECTION_TYPE"]
    propose_path = f"/contracts/{cid}/subtype-proposals"
    accept_template = f"/contracts/{cid}/subtype-proposals/{{id}}/accept"
    id_field = "proposal_id"

elif CMD == "endpoint-shift":
    cid = must("CONTRACT", "contract")
    propose_path = f"/contracts/{cid}/endpoint-proposals"
    propose_body = {
        "new_owner_part": must("NEW_OWNER", "new-owner"),
        "new_counterparty_part": must("NEW_COUNTERPARTY", "new-counterparty"),
        "rationale": must("RATIONALE", "rationale (or --rationale-file)"),
    }
    accept_template = f"/contracts/{cid}/endpoint-proposals/{{id}}/accept"
    id_field = "proposal_id"

elif CMD == "body-bump":
    cid = must("CONTRACT", "contract")
    md_path = must("MD", "md")
    propose_path = f"/contracts/{cid}/proposals"
    propose_body = {
        "version": must("VERSION", "version"),
        "markdown": pathlib.Path(md_path).read_text(),
    }
    accept_template = f"/contracts/{cid}/proposals/{{id}}/accept"
    id_field = "version"

else:
    sys.exit(
        f"unknown subcommand: {CMD!r} (one of: name-shift, "
        "part-subtype-shift, contract-subtype-shift, endpoint-shift, "
        "body-bump)"
    )

print(f"=== propose: POST {propose_path} ===", file=sys.stderr)
status, data = http("POST", propose_path, body=propose_body)
if status not in (200, 201):
    sys.exit(f"propose failed: {status} {data}")
print(json.dumps(data, indent=2))

if not SINGLE_OPERATOR:
    print(
        "\n--single-operator not passed; stopping after propose. "
        f"Hand off the {id_field} above to the second party for accept.",
        file=sys.stderr,
    )
    sys.exit(0)

ident = data.get(id_field)
if ident is None:
    sys.exit(f"propose response is missing {id_field!r}: {data}")
accept_path = accept_template.format(id=ident) + "?single_operator=true"
print(f"\n=== accept: POST {accept_path} ===", file=sys.stderr)
status, data = http("POST", accept_path)
if status not in (200, 201):
    sys.exit(
        f"accept failed: {status} {data}\n"
        f"the proposal {ident} is still open; re-run accept manually "
        "after fixing the cause."
    )
print(json.dumps(data, indent=2))

override = data.get("single_operator_override")
if override is not True:
    print(
        "\nwarning: response did not echo single_operator_override=true",
        file=sys.stderr,
    )
PY
