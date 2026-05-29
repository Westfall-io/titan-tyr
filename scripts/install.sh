#!/usr/bin/env bash
# Bootstrap script — install the WatcherVault skill catalog as a
# Claude Code plugin in one command.
#
# Usage (locally):
#   ./scripts/install.sh
#
# Eventual hosted usage (after the mimiron-side ticket lands a
# served copy on watchervault.digitalforge.app):
#   curl -fsSL https://watchervault.digitalforge.app/install.sh | bash
#
# What it does:
#
# 1. Declaratively registers the marketplace in ~/.claude/settings.json
#    via the documented `extraKnownMarketplaces` field — no slash
#    command needed.
# 2. Calls `claude plugin install watchervault@watchervault --scope user`
#    to persistently install the plugin (non-interactive CLI subcommand).
#
# After this, every Claude Code session has the `/watchervault:<skill>`
# family addressable; no manual `/plugin install` step.
#
# What it does NOT do (yet):
#
# - Mint a titan-tyr auth token. Token provisioning is a human-led
#   admin operation by design (agents-don't-self-mint principle). The
#   mimiron v2 ticket extends this script with an OAuth-backed token
#   mint endpoint; until then, get a token out-of-band from a human
#   admin and put it in your env.
#
# Requirements:
#   - claude CLI (`claude --version` works)
#   - jq (for safe JSON merge of ~/.claude/settings.json)

set -euo pipefail

MARKETPLACE_NAME="watchervault"
MARKETPLACE_REPO="Westfall-io/titan-tyr"
PLUGIN_NAME="watchervault"
PLUGIN_REF="${WATCHERVAULT_PLUGIN_REF:-}"   # optional pin: e.g. "watchervault-v1.0.0"

# --- Pre-flight ---

command -v claude >/dev/null 2>&1 || {
  echo "::error:: claude CLI not found. Install from https://claude.ai/download then re-run." >&2
  exit 1
}

command -v jq >/dev/null 2>&1 || {
  echo "::error:: jq not found. Install via your package manager (brew install jq / apt-get install jq) then re-run." >&2
  exit 1
}

# --- Step 1: register the marketplace declaratively ---

SETTINGS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"

# Source definition. Pin to a tag if WATCHERVAULT_PLUGIN_REF is set,
# else track main.
if [ -n "$PLUGIN_REF" ]; then
  source_json=$(jq -n --arg repo "$MARKETPLACE_REPO" --arg ref "$PLUGIN_REF" \
    '{source: "github", repo: $repo, ref: $ref}')
else
  source_json=$(jq -n --arg repo "$MARKETPLACE_REPO" \
    '{source: "github", repo: $repo}')
fi

# Safe merge: preserves all existing settings.
tmp=$(mktemp)
jq --arg name "$MARKETPLACE_NAME" --argjson src "$source_json" \
   '.extraKnownMarketplaces //= {} | .extraKnownMarketplaces[$name] = {source: $src}' \
   "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"

echo "Registered marketplace '$MARKETPLACE_NAME' in $SETTINGS"

# --- Step 2: install the plugin ---

# Marketplace name + plugin name happen to be the same in our setup;
# the @ form is "plugin@marketplace".
target="${PLUGIN_NAME}@${MARKETPLACE_NAME}"
echo "Installing plugin: $target (--scope user) ..."
claude plugin install "$target" --scope user

echo
echo "✓ WatcherVault skill catalog installed."
echo
echo "Skills are now addressable as /${PLUGIN_NAME}:<skill-name> in any"
echo "Claude Code session — e.g. /${PLUGIN_NAME}:register-part,"
echo "/${PLUGIN_NAME}:find-part, /${PLUGIN_NAME}:learn-contract."
echo
echo "Get an auth token from your tyr admin (see docs/auth.md) and"
echo "set TITAN_TYR_URL + TITAN_TYR_TOKEN in your env."
