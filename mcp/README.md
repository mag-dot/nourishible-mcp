# nourishible-mcp (local client) — fallback connector

**This is the fallback path.** Prefer connecting the hosted remote MCP server at
**nourishible.com/mcp** if your agent supports adding a remote MCP server directly (Claude
Code: `claude mcp add --transport http nourishible <url from that page>`) — that needs no
clone, no build, and no login step; connecting the server *is* the login. Use this local
package only when your agent doesn't support remote-MCP OAuth yet.

This is a local **stdio** MCP server: you clone/build/run it yourself, and it talks to
nourishible's backend over its OAuth 2.0 Authorization Code + PKCE flow.

## Tools

| Tool | Scope | Does |
|---|---|---|
| `search_recipes` | Public, no connection needed | List recipes across every nourishible user's library, newest first, optionally filtered by a search term |
| `get_recipe` | Public, no connection needed | Fetch one recipe by id or slug from the public catalog |
| `list_my_recipes` | Your own account | List recipes in your own library, optionally filtered |
| `get_my_recipe` | Your own account | Fetch one of your own recipes by id |
| `save_recipe` | Your own account | Save a structured recipe (title/ingredients/steps/tags/…) |
| `update_recipe` | Your own account | Change one or more fields on an already-saved recipe (partial update) |
| `set_recipe_thumbnail` | Your own account | Upload a local JPEG file as a recipe's thumbnail |
| `delete_recipe` | Your own account | Remove a recipe by id |

Same tool names and scope as the hosted remote MCP server, with one deliberate difference:
`set_recipe_thumbnail` takes a local filesystem path here (this connector runs on your own
machine), while the remote server takes base64-encoded image bytes (it has no shared
filesystem with your agent).

`save_recipe`'s input schema mirrors the shape `skills/recipe-nourishible/SKILL.md`
already produces, so an agent that extracted a recipe that way can pass its output
straight through.

## Quick install

You need a nourishible account and an active session in your browser (sign up/log in at
nourishible.com first).

Copy the block below and paste it into your terminal (it's also checked in as
[`install.sh`](./install.sh), if you'd rather download and read it first). It clones this
repo (or updates it, if you already have a copy at `~/.nourishible/nourishible-mcp`),
installs and builds the MCP server, runs the one-time browser login, and registers it with
Claude Code automatically if the `claude` CLI is on your PATH — otherwise it prints the
Claude Desktop config snippet with the right path already filled in. Re-running it any
time is safe — it updates in place and re-registers.

```bash
(
set -euo pipefail
REPO_URL="https://github.com/mag-dot/nourishible-mcp.git"
INSTALL_DIR="$HOME/.nourishible/nourishible-mcp"

for bin in git node npm; do
  command -v "$bin" >/dev/null 2>&1 || { echo "Error: $bin is required." >&2; exit 1; }
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
  echo "Claude Code CLI not found. If you use Claude Desktop, add this to its MCP config:"
  echo "{ \"mcpServers\": { \"nourishible\": { \"command\": \"node\", \"args\": [\"$CLI_PATH\"] } } }"
fi
)
```

## Manual setup

If you'd rather run each step yourself:

```bash
npm install
cp .env.example .env    # defaults to the real deployed backend — see Config below
npm run login             # opens a browser, completes the OAuth/PKCE flow, stores a token
npm run build
```

This stores an access token at `~/.nourishible-mcp/config.json` (mode 0600). One login is
good for the token's lifetime (90 days) — you don't need to re-run this per Claude session.
`npm run logout` clears it.

Then point Claude Desktop/Code at the built entrypoint as a local (stdio) MCP server:

```json
{
  "mcpServers": {
    "nourishible": {
      "command": "node",
      "args": ["/absolute/path/to/nourishible-mcp/mcp/dist/cli.js"]
    }
  }
}
```

(Claude Code: `claude mcp add nourishible -- node /absolute/path/to/dist/cli.js`, or add the
same block to the relevant `.mcp.json`/settings file — see Claude Code's MCP docs.)

No further auth prompt happens inside Claude — the server reads the token stored by
`npm run login`. If that token is missing/expired, tool calls return a clear error telling
you to rerun `npm run login`, rather than failing silently.

## Config

See `.env.example`. `NOURISHIBLE_API_URL` defaults to the real deployed backend — only set
it if you're pointing this at a different environment (e.g. developing against a local
backend). `NOURISHIBLE_OAUTH_CLIENT_ID` must match a `client_id` registered on the backend,
with a redirect URI matching `http://localhost:$NOURISHIBLE_MCP_CALLBACK_PORT/callback`.

## Security & Permissions

**What this server does:**
- On `npm run login`, opens your system browser to the backend's `/oauth/authorize` (which
  redirects to a real sign-in + consent page) and runs the standard Authorization Code +
  PKCE loopback flow (the same pattern `gh`/`gcloud` CLIs use) — a local HTTP server on
  `NOURISHIBLE_MCP_CALLBACK_PORT` catches the redirect, then exchanges the code for a token
  server-to-server. Your nourishible password is never seen by this tool — the flow
  delegates entirely to your already-signed-in browser session and nourishible's own login
  form.
- Stores the resulting access token at `~/.nourishible-mcp/config.json`, mode `0600`
  (owner-read/write only). The token is scoped to `recipes:read recipes:write` on your
  account specifically — not a full account credential, not usable for anything else.
- Sends that token as a Bearer header on every authenticated tool call to the configured
  `NOURISHIBLE_API_URL`, and nowhere else. The two public tools (`search_recipes`,
  `get_recipe`) send no auth header at all.
- On `npm run logout`, calls `DELETE /oauth/token` to revoke the token server-side
  *before* deleting the local file — a copy of the token made before logout stops working
  too, not just the copy on this machine.

**What this server does NOT do:**
- Does not read, store, or transmit your nourishible password at any point.
- Does not call any third-party API beyond `NOURISHIBLE_API_URL` — no telemetry, no
  analytics endpoint.
- Does not act on your account beyond the recipe operations above — no access to billing,
  other users' data, or account settings.
- Does not auto-refresh an expired/revoked token silently — a 401 from the backend
  surfaces as a clear "run `npm run login` again" error to whatever agent called the tool,
  rather than failing opaquely.

## Not yet done

- ChatGPT doesn't speak MCP the same way Claude does — a ChatGPT-side connector isn't
  built here; this package is Claude/MCP-only for now.
- Not published to npm; the install steps above assume a local clone/build.
