#!/usr/bin/env bash
# Bulk-tag/claim parts and contracts in one pass (#59).
#
# The skills update one row at a time. After landing a new project (#44)
# or after a created_by_actor backfill (#54) every consumer needs the
# same sweep: walk the catalog, set project and/or X-Actor on each row.
# This script centralises the loop, the filter, the dry-run table, and
# the confirmation gate so it stops being reinvented per consumer.
#
# Usage:
#   scripts/bulk-claim-rows.sh [flags]
#
# Flags:
#   --project <slug | __none__>    Set every touched row's project tag.
#                                  __none__ clears the tag.
#                                  Omit to leave project unchanged.
#   --actor <identity>             Sent as X-Actor on every PUT. Claims
#                                  rows where created_by_actor IS NULL
#                                  (first-write-wins, #54). Falls back
#                                  to TITAN_TYR_ACTOR if unset.
#   --kind parts|contracts|both    Default: both.
#   --current-project <slug | __none__>
#                                  Only touch rows currently in this
#                                  project. Uses server-side ?project=
#                                  filter; cheap.
#   --current-actor <identity | __none__>
#                                  Only touch rows whose
#                                  created_by_actor matches. __none__
#                                  selects unattributed rows. Filtered
#                                  client-side after pagination.
#   --yes                          Skip the confirmation gate. Use only
#                                  in scripts; humans should eyeball
#                                  the dry-run table.
#
# Env:
#   TITAN_TYR_URL    required (e.g. http://localhost:18000)
#   TITAN_TYR_TOKEN  default sysmlv2
#   TITAN_TYR_ACTOR  fallback for --actor
#
# Exit codes:
#   0  sweep applied (or dry-run shown and declined)
#   1  any PUT failed; partial sweep — re-run after fixing
#   2  bad arguments / missing env

set -euo pipefail

project=""
project_set=0
actor=""
kind="both"
current_project=""
current_project_set=0
current_actor=""
current_actor_set=0
assume_yes=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) project="$2"; project_set=1; shift 2 ;;
    --actor) actor="$2"; shift 2 ;;
    --kind) kind="$2"; shift 2 ;;
    --current-project) current_project="$2"; current_project_set=1; shift 2 ;;
    --current-actor) current_actor="$2"; current_actor_set=1; shift 2 ;;
    --yes|-y) assume_yes=1; shift ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed 's/^# //; s/^#//'; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

case "$kind" in
  parts|contracts|both) ;;
  *) echo "--kind must be parts|contracts|both" >&2; exit 2 ;;
esac

if [[ -z "${TITAN_TYR_URL:-}" ]]; then
  echo "TITAN_TYR_URL is not set" >&2
  exit 2
fi
url="$TITAN_TYR_URL"
token="${TITAN_TYR_TOKEN:-sysmlv2}"
[[ -z "$actor" ]] && actor="${TITAN_TYR_ACTOR:-}"

if [[ $project_set -eq 0 && -z "$actor" ]]; then
  echo "nothing to do: pass --project and/or --actor (or set TITAN_TYR_ACTOR)" >&2
  exit 2
fi

# Hand off to python for paging, filtering, and the PUT loop. Bash for
# arg-parsing and curl plumbing; python for everything that involves
# JSON. Pass config via env to keep quoting sane.
URL="$url" TOKEN="$token" ACTOR="$actor" \
PROJECT="$project" PROJECT_SET="$project_set" \
KIND="$kind" \
CURRENT_PROJECT="$current_project" CURRENT_PROJECT_SET="$current_project_set" \
CURRENT_ACTOR="$current_actor" CURRENT_ACTOR_SET="$current_actor_set" \
ASSUME_YES="$assume_yes" \
python3 - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ["URL"].rstrip("/")
TOKEN = os.environ["TOKEN"]
ACTOR = os.environ["ACTOR"]
PROJECT = os.environ["PROJECT"]
PROJECT_SET = os.environ["PROJECT_SET"] == "1"
KIND = os.environ["KIND"]
CURRENT_PROJECT = os.environ["CURRENT_PROJECT"]
CURRENT_PROJECT_SET = os.environ["CURRENT_PROJECT_SET"] == "1"
CURRENT_ACTOR = os.environ["CURRENT_ACTOR"]
CURRENT_ACTOR_SET = os.environ["CURRENT_ACTOR_SET"] == "1"
ASSUME_YES = os.environ["ASSUME_YES"] == "1"

NONE = "__none__"


def http(method, path, body=None, *, send_actor=False):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if send_actor and ACTOR:
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
        body_txt = e.read().decode("utf-8", "replace")
        return e.code, body_txt


def list_all(resource):
    """Page through /parts or /contracts, applying server-side
    project filter when present."""
    items = []
    cursor = None
    params = {"limit": "100"}
    if CURRENT_PROJECT_SET:
        params["project"] = CURRENT_PROJECT
    while True:
        q = dict(params)
        if cursor:
            q["after"] = cursor
        status, data = http("GET", f"/{resource}?{urllib.parse.urlencode(q)}")
        if status != 200:
            sys.exit(f"GET /{resource} failed: {status} {data}")
        items.extend(data["results"])
        cursor = data.get("next")
        if not cursor:
            break
    return items


def matches_actor_filter(row):
    if not CURRENT_ACTOR_SET:
        return True
    cur = row.get("created_by_actor")
    if CURRENT_ACTOR == NONE:
        return cur is None
    return cur == CURRENT_ACTOR


def bump_patch(version):
    major, minor, patch = (int(x) for x in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def project_change_for(row):
    """Returns (will_change, new_value_for_table) for the project field
    on this row. None means 'unchanged' (omitted from PUT)."""
    if not PROJECT_SET:
        return False, row.get("project")
    new = None if PROJECT == NONE else PROJECT
    return new != row.get("project"), new


def actor_change_for(row):
    """X-Actor only takes effect on rows where created_by_actor is null
    (first-write-wins). Returns (will_claim, new_value)."""
    if not ACTOR:
        return False, row.get("created_by_actor")
    if row.get("created_by_actor") is None:
        return True, ACTOR
    return False, row.get("created_by_actor")


def plan(kind, rows):
    """Build (touch, skip) lists. A row is touched iff something would
    actually change for it under this sweep."""
    touch, skip = [], []
    for r in rows:
        if not matches_actor_filter(r):
            continue
        proj_change, proj_new = project_change_for(r)
        actor_change, actor_new = actor_change_for(r)
        if not (proj_change or actor_change):
            skip.append((r, "no-op"))
            continue
        touch.append({
            "row": r,
            "proj_change": proj_change,
            "proj_new": proj_new,
            "actor_change": actor_change,
            "actor_new": actor_new,
        })
    return touch, skip


def render_table(kind, touch):
    if not touch:
        return f"({kind}: nothing to change)"
    handle_w = max(len(_handle(kind, t["row"])) for t in touch)
    handle_w = max(handle_w, len("handle"))
    lines = [f'{"handle":<{handle_w}}  {"project":<24}  actor']
    for t in touch:
        r = t["row"]
        cur_proj = r.get("project") or "-"
        new_proj = t["proj_new"] or "-"
        proj_cell = (
            f"{cur_proj} → {new_proj}" if t["proj_change"] else cur_proj
        )
        cur_actor = r.get("created_by_actor") or "-"
        new_actor = t["actor_new"] or "-"
        actor_cell = (
            f"{cur_actor} → {new_actor}" if t["actor_change"] else cur_actor
        )
        lines.append(
            f"{_handle(kind, r):<{handle_w}}  {proj_cell:<24}  {actor_cell}"
        )
    return "\n".join(lines)


def _handle(kind, row):
    if kind == "parts":
        return row["name"]
    return row["contract_id"][:8]


def apply_contract(t):
    body = {}
    if t["proj_change"]:
        body["project"] = t["proj_new"]
    status, data = http(
        "PUT",
        f"/contracts/{t['row']['contract_id']}",
        body=body,
        send_actor=t["actor_change"],
    )
    return status, data


def apply_part(t):
    name = t["row"]["name"]
    status, detail = http("GET", f"/parts/{name}")
    if status != 200:
        return status, detail
    body = {
        "version": bump_patch(detail["version"]),
        "markdown": detail["markdown"],
    }
    if t["proj_change"]:
        body["project"] = t["proj_new"]
    status, data = http(
        "PUT", f"/parts/{name}", body=body, send_actor=t["actor_change"]
    )
    return status, data


def main():
    do_parts = KIND in ("parts", "both")
    do_contracts = KIND in ("contracts", "both")

    plans = {}
    if do_parts:
        plans["parts"] = plan("parts", list_all("parts"))
    if do_contracts:
        plans["contracts"] = plan("contracts", list_all("contracts"))

    print("=== bulk-claim-rows: dry run ===")
    print(f"server:  {URL}")
    print(f"actor:   {ACTOR or '(none)'}")
    if PROJECT_SET:
        print(f"project: -> {PROJECT}")
    else:
        print("project: (unchanged)")
    if CURRENT_PROJECT_SET:
        print(f"filter:  current_project={CURRENT_PROJECT}")
    if CURRENT_ACTOR_SET:
        print(f"filter:  current_actor={CURRENT_ACTOR}")
    print()

    total_touch = 0
    total_skip = 0
    for kind, (touch, skip) in plans.items():
        print(f"--- {kind} ({len(touch)} to change, {len(skip)} unchanged) ---")
        print(render_table(kind, touch))
        print()
        total_touch += len(touch)
        total_skip += len(skip)

    if total_touch == 0:
        print("nothing would change. exiting.")
        return 0

    if not ASSUME_YES:
        try:
            ans = input(f"apply {total_touch} change(s)? [y/N] ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("declined.")
            return 0

    print()
    print("=== applying ===")
    failures = 0
    for kind, (touch, _) in plans.items():
        applier = apply_part if kind == "parts" else apply_contract
        for t in touch:
            handle = _handle(kind, t["row"])
            status, data = applier(t)
            if status in (200, 201):
                print(f"  ok    {kind:<9} {handle}")
            else:
                failures += 1
                print(f"  FAIL  {kind:<9} {handle} -> {status} {data}")

    print()
    print(
        f"summary: changed {total_touch - failures}, "
        f"skipped {total_skip}, failed {failures}"
    )
    return 1 if failures else 0


sys.exit(main())
PY
