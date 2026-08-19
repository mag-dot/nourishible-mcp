# Install nourishible (agent instructions)

**This file is written for an AI agent, not a person.** If you are a user, you don't need
to read it — paste this into your agent instead, and it will do the whole setup:

> Set up nourishible for me by reading and following
> https://raw.githubusercontent.com/mag-dot/nourishible-mcp/main/INSTALL.md

---

## Agent: read this part

You are setting up nourishible for the user. There are **two pieces, and both are
required** — a recipe can't be saved with only one of them:

1. **The remote MCP server** `https://backend-api-production-c967.up.railway.app/mcp` —
   saving, under the user's own nourishible account. Connecting it *is* the login.
2. **The `recipe-nourishible` skill** — extraction. It watches the video and writes the
   structured recipe, then calls the MCP server's tools to save it.

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
plugin that bundles the skill *and* the MCP registration:

```
/plugin marketplace add mag-dot/nourishible-mcp
/plugin install nourishible@nourishible-mcp
```

These are slash commands the **user** types; you can't run them for them. Print both lines
and ask the user to run them, then continue to "Step 3 — verify and report".

## Step 1 — register the MCP server

URL, used verbatim everywhere below:

```
https://backend-api-production-c967.up.railway.app/mcp
```

Transport is streamable HTTP. Pick the row that matches the agent you're running as:

| Agent | What to do |
| --- | --- |
| Claude Code (not using the plugin) | `claude mcp add --transport http --scope user nourishible https://backend-api-production-c967.up.railway.app/mcp` |
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
      "url": "https://backend-api-production-c967.up.railway.app/mcp"
    }
  }
}
```

Merge it into the existing `mcpServers` object — read the file first and preserve every
other server already in it. Create the file with just this content if it doesn't exist.

Most clients only pick up a config change on restart. Say so plainly if that applies.

## Step 2 — install the skill

The skill lives in this repo at `skills/recipe-nourishible/`. Copy that directory —
`SKILL.md` plus its `scripts/` — into wherever the agent you're running as loads skills
from:

| Agent | Skill directory |
| --- | --- |
| Claude Code | `~/.claude/skills/recipe-nourishible/` (all projects) or `.claude/skills/recipe-nourishible/` (this project only) |
| Claude Desktop / claude.ai | Not a directory — it's a UI upload. See "Claude Desktop" below |
| Cursor, Windsurf, and other agents with a skills or rules directory | That agent's equivalent directory, one folder per skill |
| An agent with no skill concept | Leave the repo checked out somewhere stable and tell the user to point you at `SKILL.md` when they want a recipe |

The skill's full instructions are also published at
`https://raw.githubusercontent.com/mag-dot/nourishible-mcp/main/SKILL.md` — a byte-identical
copy of `skills/recipe-nourishible/SKILL.md`. An agent that can fetch a URL but can't clone
or write files can read the recipe workflow straight from there. It won't have the bundled
`scripts/`, so the download/frames/transcript steps still need a real install.

A shell-capable agent can do the whole thing like this (adjust the destination to the row
above):

```bash
tmp="$(mktemp -d)"
git clone --depth 1 https://github.com/mag-dot/nourishible-mcp "$tmp/nourishible-mcp"
mkdir -p ~/.claude/skills
rm -rf ~/.claude/skills/recipe-nourishible
cp -R "$tmp/nourishible-mcp/skills/recipe-nourishible" ~/.claude/skills/recipe-nourishible
rm -rf "$tmp"
```

`rm -rf` on the destination replaces any older copy of this same skill. Check what's
there first, and if the directory exists but isn't a previous install of this skill, stop
and ask instead of deleting it.

**Claude Desktop / claude.ai:** skills are uploaded as a `.skill` bundle through the UI,
which you can't drive. Build the bundle from a clean checkout —

```bash
bash skills/recipe-nourishible/scripts/build-skill.sh
```

— and tell the user to upload the resulting `dist/recipe-nourishible.skill` in the skills
UI. (The build refuses to run on a dirty working tree; that's intentional.)

**macOS-only note, worth passing on:** Instagram extraction goes through a local screen
capture pipeline that only runs on macOS. YouTube and Xiaohongshu work everywhere. The
skill installs its own dependencies on first use — don't pre-install anything here.

## Step 3 — verify and report

1. **Skill:** confirm `SKILL.md` and `scripts/` landed in the destination directory.
2. **MCP:** after whatever restart the client needs, `save_recipe`, `update_recipe`,
   `set_recipe_thumbnail`, `list_my_recipes`, `get_my_recipe`, `search_recipes`, and
   `get_recipe` should be visible as callable tools.
3. **Sign-in:** don't try to trigger it now. The first time a save actually runs, the
   agent opens the user's browser to a nourishible sign-in page and an approve screen.
   That step is tied to the user's own account and can't be done on their behalf — say
   it's coming, so it isn't a surprise.

Then tell the user, in a few lines: what you installed, anything they still have to do
themselves (restart, GUI steps, the `.skill` upload), and that they can now paste a
cooking video link and ask for it to be saved to their nourishible library.
