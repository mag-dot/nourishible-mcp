# Install nourishible (agent instructions)

**This file is written for an AI agent, not a person.** If you are a user, you don't need
to read it — paste this into your agent instead, and it will do the whole setup:

> Set up nourishible for me by reading and following https://mcp.nourishible.com/

---

## Agent: read this part

You are setting up nourishible for the user. There are **two MCP connections, and both
are required** — a recipe can't be saved with only one of them:

1. **The remote MCP server** `https://mcp.nourishible.com/mcp` —
   saving, under the user's own nourishible account. Connecting it *is* the login.
2. **The local `nourishible-mcp-local` server** — extraction plus the recipe workflow. It
   watches the video (or reads Instagram carousel slides), returns evidence for the agent
   to structure, then the agent calls the hosted tools to save it. The standalone skill is
   retained as a compatibility fallback for clients without local MCP support.

Do both in this one pass. Don't stop after the first, and don't ask the user to come back
for a second round.

**Ground rules:**

- **Do as much as you actually can**, then report. Some steps need a GUI or a browser you
  can't drive — for those, print the exact thing the user must click or paste, in one
  block at the end, rather than pretending it's done.
- **Never ask the user for a password, token, or API key.** There is no key in this setup.
  The sign-in is a browser OAuth flow the user completes themselves.
- **Don't hand-roll the OAuth flow** from raw HTTP calls. The agent's own MCP client does
  it; anything you write by hand is a second implementation that will drift and break.
- If a step is already done (server already registered, skill already present), say so and
  move on — everything here is safe to re-run.

## Claude Code: one command does both

If you are Claude Code, skip the two steps below entirely — this repo is packaged as a
plugin that bundles the local extraction MCP, compatibility skill, and hosted MCP registration:

```
/plugin marketplace add mag-dot/nourishible-mcp
/plugin install nourishible@nourishible-mcp
```

These are slash commands the **user** types; you can't run them for them. Print both lines
and ask the user to run them, then continue to "Step 3 — verify and report".

## Step 1 — register the MCP server

URL, used verbatim everywhere below:

```
https://mcp.nourishible.com/mcp
```

Transport is streamable HTTP. Pick the row that matches the agent you're running as:

| Agent | What to do |
| --- | --- |
| Claude Code (not using the plugin) | `claude mcp add --transport http --scope user nourishible https://mcp.nourishible.com/mcp` |
| Cursor | Merge the JSON block below into `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` (this project) |
| Windsurf, Cline, and other JSON-configured clients | Same JSON block, in that client's MCP config file |
| Gemini CLI | Merge the JSON block into the `mcpServers` object in `~/.gemini/settings.json` |
| Codex CLI | Add the equivalent entry to `~/.codex/config.toml` (`[mcp_servers.nourishible]` with the same URL) |
| Claude Desktop | **You can't do this one.** Tell the user: Settings → Connectors → Add custom connector → paste the URL above |
| Anything else | Look up that agent's "add a remote/HTTP MCP server" step; if you can't determine it, give the user the URL and say it needs to be added as a remote HTTP MCP server named `nourishible` |

JSON entry, for any client configured by file:

```json
{
  "mcpServers": {
    "nourishible": {
      "type": "http",
      "url": "https://mcp.nourishible.com/mcp"
    }
  }
}
```

Merge it into the existing `mcpServers` object — read the file first and preserve every
other server already in it. Create the file with just this content if it doesn't exist.

Most clients only pick up a config change on restart. Say so plainly if that applies.

## Step 2 — install the local MCP server

Install the package with Python 3.10 or newer:

```bash
python3 -m pip install "git+https://github.com/mag-dot/nourishible-mcp.git"
```

Then register a local stdio MCP server named `nourishible-local` whose command is
`nourishible-mcp-local`. Use the client's normal local-MCP configuration flow. For JSON
clients the entry is:

```json
{
  "mcpServers": {
    "nourishible-local": {
      "command": "nourishible-mcp-local",
      "args": []
    }
  }
}
```

Use the absolute path returned by `command -v nourishible-mcp-local` if the client starts
with a restricted `PATH`. The installed wheel contains `SKILL.md`, every reference, and
all extraction/capture scripts. The server publishes the workflow at
`nourishible://recipe-workflow`, so there is no separate skill-copy or upload step.

Clients without local stdio MCP support may still install the compatibility skill from
`skills/recipe-nourishible/` using their normal skill mechanism.

**macOS-only note, worth passing on:** Instagram extraction goes through a local screen
capture pipeline that only runs on macOS — this covers both Reels and multi-image
carousels. YouTube and Xiaohongshu work everywhere. The skill installs its own
dependencies on first use — don't pre-install anything here.

## Step 3 — verify and report

1. **Local MCP:** confirm `recipe_setup_status`, `extract_recipe_evidence`,
   `instagram_capture_instructions`, and the `nourishible://recipe-workflow` resource are visible.
2. **Hosted MCP:** after whatever restart the client needs, `save_recipe`, `update_recipe`,
   `set_recipe_thumbnail`, `list_my_recipes`, `get_my_recipe`, `search_recipes`, and
   `get_recipe` should be visible as callable tools.
3. **Sign-in: trigger it now, don't defer it.** Call `list_my_recipes` (harmless, read-only,
   costs the user nothing) to finish the install with the account actually connected instead
   of leaving it as a surprise on the user's first real save. This call needs the user's own
   account, so it's what starts the agent's browser-based OAuth flow — a real nourishible
   sign-in page, then an "Allow" screen naming this connection. Tell the user before calling
   it ("one more step — this'll open your browser to sign in and approve the connection")
   rather than opening a browser on them with no warning. If the client can't complete OAuth
   from a background tool call (some GUI clients require the user to trigger the first
   authenticated action themselves), say so plainly and tell the user to paste a video link
   once to finish connecting, rather than pretending this step is done.
   **Never construct this sign-in URL by hand** — `nourishible.com/connect` only works with
   the OAuth parameters the agent's own MCP client generates during this handshake; a bare
   link to it is a dead end, not a shortcut.

Then tell the user, in a few lines: what you installed, anything they still have to do
themselves (restart, GUI steps, the `.skill` upload, finishing sign-in), and that they can
now paste a cooking video or Instagram carousel link and ask for it to be saved to their
nourishible library.
