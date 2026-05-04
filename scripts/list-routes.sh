#!/usr/bin/env bash
# Boot the FastAPI app from src and dump its routes (method + path).
# Filter by a substring of the path with the optional <filter> arg.
#
# Usage:
#   scripts/list-routes.sh                # all routes
#   scripts/list-routes.sh /contracts     # routes whose path contains '/contracts'
#
# Useful as a sanity check after adding or renaming a route. Runs
# entirely against local source — no live API call.

set -euo pipefail

filter="${1:-}"

# Prefer the project venv if present; fall back to whatever python3 the
# shell finds. Run from the repo root so `from src.main` resolves.
cd "$(git rev-parse --show-toplevel)"

py=".venv/bin/python"
[[ -x "$py" ]] || py="python3"

FILTER="$filter" "$py" -c '
import os
from src.main import create_app
app = create_app()
filt = os.environ.get("FILTER", "")
rows = []
for r in app.routes:
    path = getattr(r, "path", None)
    if path is None:
        continue
    if filt and filt not in path:
        continue
    methods = sorted(getattr(r, "methods", set()) or set()) or ["-"]
    rows.append((path, ",".join(methods)))
rows.sort()
width = max((len(p) for p, _ in rows), default=0)
for path, methods in rows:
    print(f"{path.ljust(width)}  {methods}")
'
