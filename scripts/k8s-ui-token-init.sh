#!/usr/bin/env sh
# Reference init-container script for SPA-style consumers (#81 / #82 / #84
# follow-up).
#
# **Prefer `python -m src.cli k8s-init-token` (#89) for new deployments.**
# The CLI subcommand does the same flow inside the existing titan-tyr
# image — no separate init image, no curl/kubectl additions. This shell
# script is kept as an alternative for deployers who want a tiny
# alpine-based init image and don't want Python in the init container.
#
# **Owner: titan-archaedas (devops)**, not titan-tyr. Lives here as a
# reference implementation that stays in sync with the API surface as
# titan-tyr evolves; the deploying team copies + adapts in the
# titan-archaedas repo's Helm chart / Kustomize overlay (per the
# project memory: titan-tyr is app-layer, ops belongs to devops).
#
# Idempotent shape: on every pod start, look at the existing UI Secret;
# if its token still authenticates, reuse it; otherwise issue a new
# token via POST /auth-tokens, persist into the K8s Secret, and hand
# off to the main container via a shared emptyDir volume.
#
# Why both a Secret and an emptyDir hand-off?
# - The K8s Secret is the **persistence** layer: re-reading the same
#   token across pod restarts skips the issue-and-write dance.
# - The emptyDir is the **runtime** hand-off: `envFrom: secretKeyRef`
#   is evaluated at pod-create time, so on first deploy (when the
#   Secret is empty) the env value would be empty even after the init
#   patches the Secret. The emptyDir lives across both containers,
#   so the main container can read the just-issued token from a file
#   without a pod restart.
#
# Inputs (set via env / mounted volumes in the Pod spec):
#   TITAN_TYR_URL         API base URL.
#   ADMIN_TOKEN_FILE      Path to the admin bearer (default /admin/TITAN_TYR_TOKEN).
#                         Mounted from a separate Secret (e.g. titan-tyr-bootstrap-admin),
#                         visible only to the init container.
#   UI_SECRET_NAME        K8s Secret name to read/write the UI token (e.g.
#                         titan-mimiron-spa-token).
#   POD_NAMESPACE         The pod's namespace (downward-API).
#   UI_TOKEN_FILE         Path where the UI Secret is mounted as a file
#                         (default /ui-secret/TITAN_TYR_TOKEN). Optional on
#                         first deploy when the Secret is empty.
#   HANDOFF_FILE          Where to write the live token for the main container
#                         (default /handoff/TITAN_TYR_TOKEN).
#
# RBAC: the ServiceAccount running this Pod must have `get` and
# `patch` on the specific Secret named in UI_SECRET_NAME (scope it
# down via `resourceNames:` in the Role; do NOT grant cluster-wide
# secrets:patch).
#
# Image requirements: a small base with `curl`, `python3`, `kubectl`,
# `base64`. alpine/k8s:* works; a purpose-built image is fine too.
#
# Out of scope here (file separately if/when you want them):
# - Forced rotation cadence. Today rotation only happens when the
#   probe fails. Add an `--expires-at` to the issue payload below if
#   you want time-based rotation.
# - Sweep of historical revoked tokens. They sit in the auth_tokens
#   table indefinitely; cheap (small partial index) but tidy as a
#   periodic CronJob.

set -eu

API_URL="${TITAN_TYR_URL:?TITAN_TYR_URL must be set}"
ADMIN_TOKEN_FILE="${ADMIN_TOKEN_FILE:-/admin/TITAN_TYR_TOKEN}"
UI_SECRET_NAME="${UI_SECRET_NAME:?UI_SECRET_NAME must be set}"
UI_SECRET_NS="${POD_NAMESPACE:?POD_NAMESPACE must be set (use the downward API)}"
UI_TOKEN_FILE="${UI_TOKEN_FILE:-/ui-secret/TITAN_TYR_TOKEN}"
HANDOFF_FILE="${HANDOFF_FILE:-/handoff/TITAN_TYR_TOKEN}"

probe_existing() {
  # Probe with the current Secret token. Returns 0 if it authenticates,
  # non-zero otherwise. Trailing slash is stripped from API_URL above.
  curl -fsS -H "Authorization: Bearer $1" \
       "${API_URL%/}/parts?limit=1" >/dev/null 2>&1
}

# Step 1: try to reuse an existing live token.
if [ -s "$UI_TOKEN_FILE" ]; then
  EXISTING="$(cat "$UI_TOKEN_FILE")"
  if probe_existing "$EXISTING"; then
    echo "[init] existing UI token is live; reusing." >&2
    printf '%s' "$EXISTING" > "$HANDOFF_FILE"
    exit 0
  fi
  echo "[init] existing UI token failed probe (expired/revoked?); rotating." >&2
fi

# Step 2: issue a fresh token via the admin bearer.
if [ ! -s "$ADMIN_TOKEN_FILE" ]; then
  echo "[init] ERROR: admin token file $ADMIN_TOKEN_FILE is empty or missing." >&2
  echo "[init] devops must seed Secret titan-tyr-bootstrap-admin" >&2
  echo "[init] from a server-side 'python -m src.cli issue-token' run." >&2
  exit 1
fi
ADMIN="$(cat "$ADMIN_TOKEN_FILE")"

RESPONSE="$(curl -fsS -X POST \
  -H "Authorization: Bearer $ADMIN" \
  -H "Content-Type: application/json" \
  --data '{"actor":"titan-mimiron-spa","description":"UI read-only token; rotated by k8s init container","scopes":["read"]}' \
  "${API_URL%/}/auth-tokens")"

PLAINTEXT="$(printf '%s' "$RESPONSE" | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')"

# Step 3: persist into the K8s Secret so future pod starts can reuse.
B64="$(printf '%s' "$PLAINTEXT" | base64 | tr -d '\n')"
kubectl patch secret "$UI_SECRET_NAME" \
  --namespace "$UI_SECRET_NS" \
  --type merge \
  -p "{\"data\":{\"TITAN_TYR_TOKEN\":\"$B64\"}}"

# Step 4: hand off to the main container via the shared emptyDir.
printf '%s' "$PLAINTEXT" > "$HANDOFF_FILE"
echo "[init] new UI token issued + persisted to Secret $UI_SECRET_NAME." >&2
