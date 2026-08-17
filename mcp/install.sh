#!/usr/bin/env bash
# nourishible local MCP connector — one-paste installer.
#
# This is the FALLBACK path — see mcp/README.md. Prefer connecting the
# hosted remote MCP server (nourishible.com/mcp) if your agent supports
# adding a remote MCP server directly; that needs no clone/build/login at
# all. Use this script only when it doesn't.
#
# Clones nourishible-mcp (or updates an existing copy), builds the MCP
# server, runs the one-time browser login, and registers it with your
# agent. Safe to re-run any time — it reuses/updates whatever it already
# installed instead of duplicating it.
#
# Prerequisites this script does NOT set up: git and Node.js/npm.

set -euo pipefail

REPO_URL="https://github.com/mag-dot/nourishible-mcp.git"
INSTALL_DIR="$HOME/.nourishible/nourishible-mcp"

for bin in git node npm; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Error: $bin is required but wasn't found on your PATH. Install it and re-run this script." >&2
    exit 1
  fi
done

if [ -d "$INSTALL_DIR/.git" ]; then
  echo "==> Updating existing install at $INSTALL_DIR"
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "==> Cloning nourishible-mcp into $INSTALL_DIR"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR/mcp"
[ -f .env ] || cp .env.example .env

echo "==> Installing dependencies"
npm install --no-fund --no-audit

echo "==> Building"
npm run build

echo
echo "==> Signing in to nourishible (opens your browser)"
npm run login

CLI_PATH="$(pwd)/dist/cli.js"

echo
if command -v claude >/dev/null 2>&1; then
  echo "==> Registering with Claude Code"
  claude mcp remove nourishible >/dev/null 2>&1 || true
  claude mcp add nourishible -- node "$CLI_PATH"
  echo
  echo "Done! Ask Claude to save a recipe and it'll use the nourishible connector."
else
  cat <<EOF
Claude Code CLI not found, so this couldn't auto-register.

If you use Claude Code, install its CLI and re-run this script, or run:
  claude mcp add nourishible -- node "$CLI_PATH"

If you use Claude Desktop, add this to its MCP config file instead:
{
  "mcpServers": {
    "nourishible": {
      "command": "node",
      "args": ["$CLI_PATH"]
    }
  }
}
EOF
fi
