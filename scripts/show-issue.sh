#!/usr/bin/env bash
# Pretty-print a GitHub issue: title, state, labels, body, then comments.
#
# Usage:
#   scripts/show-issue.sh <issue_number>
#
# Uses the gh CLI; assumes the current dir is inside the target repo
# (gh resolves the repo from git remotes by default).

set -euo pipefail

num="${1:?usage: show-issue.sh <issue_number>}"

gh issue view "$num" --json title,state,body,labels,comments \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)
labels = [l["name"] for l in d.get("labels", [])]
title = d["title"]
state = d["state"]
print("title:  " + title)
print("state:  " + state)
print("labels: " + str(labels))
print("---")
print(d["body"])
comments = d.get("comments", [])
if comments:
    print("=== comments ===")
    for c in comments:
        login = c["author"]["login"]
        ts = c["createdAt"]
        print("\n[" + login + " @ " + ts + "]")
        print(c["body"])
'
