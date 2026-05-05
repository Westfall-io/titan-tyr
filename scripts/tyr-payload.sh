#!/usr/bin/env bash
# JSON-payload assembler for register/update part/contract calls (#63).
#
# Replaces the inline `python3 -c "import json; ..."` pattern that
# every register/update skill currently inlines. Reads the markdown
# body from a file, takes the structured fields as flags, emits JSON
# to stdout (default) or to --out FILE.
#
# Subcommands:
#   register-part      --md FILE --name N --subtype S [--repo-uri U]
#                      [--issue-tracker-uri U] [--aliases a,b,c]
#                      [--version V] [--project P]
#   update-part        --md FILE --version V [--repo-uri U]
#                      [--issue-tracker-uri U] [--aliases a,b,c]
#                      [--project P]
#   register-contract  --md FILE --owner O --counterparty C
#                      --subtype interaction|binding|connection
#                      [--connection-type LABEL] [--version V]
#                      [--project P]
#   update-contract    [--project P]
#
# Common flags:
#   --md FILE          Path to the markdown body file. Required for
#                      everything except update-contract.
#   --out FILE         Write JSON to FILE instead of stdout.
#
# Pipe-friendly default — stdout is the JSON, suitable for `--data @-`.
#
# Examples:
#   tyr-payload register-part --md .scratch/foo.md \
#       --name foo --subtype software --version 1.0.0 \
#       --project watchervault
#
#   tyr-payload register-part --md .scratch/foo.md ... \
#       | tyr-curl POST /parts --data @-
#
# Validation: aliases CSV is split on commas, trimmed; empty list
# becomes []. Project null/clear is expressed as `--project __none__`
# on update-* (omit the flag to leave unchanged).

set -euo pipefail

if [[ $# -lt 1 || "$1" == "-h" || "$1" == "--help" ]]; then
  sed -n '2,/^set -euo/p' "$0" | sed 's/^# //; s/^#//'
  exit 2
fi

cmd="$1"
shift

md=""
out=""
name=""
subtype=""
repo_uri=""
issue_tracker_uri=""
aliases=""
version=""
project=""
project_set=0
owner=""
counterparty=""
connection_type=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --md) md="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --name) name="$2"; shift 2 ;;
    --subtype) subtype="$2"; shift 2 ;;
    --repo-uri) repo_uri="$2"; shift 2 ;;
    --issue-tracker-uri) issue_tracker_uri="$2"; shift 2 ;;
    --aliases) aliases="$2"; shift 2 ;;
    --version) version="$2"; shift 2 ;;
    --project) project="$2"; project_set=1; shift 2 ;;
    --owner) owner="$2"; shift 2 ;;
    --counterparty) counterparty="$2"; shift 2 ;;
    --connection-type) connection_type="$2"; shift 2 ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed 's/^# //; s/^#//'; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

CMD="$cmd" MD="$md" OUT="$out" \
NAME="$name" SUBTYPE="$subtype" REPO_URI="$repo_uri" \
ISSUE_TRACKER_URI="$issue_tracker_uri" ALIASES="$aliases" \
VERSION="$version" PROJECT="$project" PROJECT_SET="$project_set" \
OWNER="$owner" COUNTERPARTY="$counterparty" \
CONNECTION_TYPE="$connection_type" \
python3 - <<'PY'
import json
import os
import pathlib
import sys

cmd = os.environ["CMD"]
md_path = os.environ["MD"]
out_path = os.environ["OUT"]
project_set = os.environ["PROJECT_SET"] == "1"
project_val = os.environ["PROJECT"]


def md_body():
    if not md_path:
        sys.exit("--md is required")
    return pathlib.Path(md_path).read_text()


def aliases_list():
    raw = os.environ["ALIASES"]
    if not raw:
        return None
    return [a.strip() for a in raw.split(",") if a.strip()]


def project_field(body):
    if not project_set:
        return
    if project_val == "__none__":
        body["project"] = None
    else:
        body["project"] = project_val


def require(name, env):
    v = os.environ[env]
    if not v:
        sys.exit(f"--{name.replace('_','-')} is required for {cmd}")
    return v


if cmd == "register-part":
    body = {
        "name": require("name", "NAME"),
        "subtype": require("subtype", "SUBTYPE"),
        "markdown": md_body(),
    }
    if os.environ["REPO_URI"]:
        body["repo_uri"] = os.environ["REPO_URI"]
    if os.environ["ISSUE_TRACKER_URI"]:
        body["issue_tracker_uri"] = os.environ["ISSUE_TRACKER_URI"]
    al = aliases_list()
    if al is not None:
        body["aliases"] = al
    if os.environ["VERSION"]:
        body["version"] = os.environ["VERSION"]
    project_field(body)

elif cmd == "update-part":
    body = {
        "version": require("version", "VERSION"),
        "markdown": md_body(),
    }
    if os.environ["REPO_URI"]:
        body["repo_uri"] = os.environ["REPO_URI"]
    if os.environ["ISSUE_TRACKER_URI"]:
        body["issue_tracker_uri"] = os.environ["ISSUE_TRACKER_URI"]
    al = aliases_list()
    if al is not None:
        body["aliases"] = al
    project_field(body)

elif cmd == "register-contract":
    body = {
        "owner_part": require("owner", "OWNER"),
        "counterparty_part": require("counterparty", "COUNTERPARTY"),
        "subtype": require("subtype", "SUBTYPE"),
        "markdown": md_body(),
    }
    if os.environ["CONNECTION_TYPE"]:
        body["connection_type"] = os.environ["CONNECTION_TYPE"]
    if os.environ["VERSION"]:
        body["version"] = os.environ["VERSION"]
    project_field(body)

elif cmd == "update-contract":
    body = {}
    project_field(body)
    if not body:
        sys.exit("update-contract: nothing to send (pass --project)")

else:
    sys.exit(
        f"unknown subcommand: {cmd!r} "
        "(register-part | update-part | register-contract | update-contract)"
    )

text = json.dumps(body, indent=2)
if out_path:
    pathlib.Path(out_path).write_text(text + "\n")
else:
    print(text)
PY
