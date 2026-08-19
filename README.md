# nourishible-mcp

Extract recipes from any cooking video with your own AI agent — Claude Code, Claude
Desktop, Cursor, or any other MCP-capable coding agent — and save them straight to your
[nourishible](https://nourishible.com) library. Your agent does the work (download, watch,
structure the recipe), so it's free and uncapped: no extraction quota, because it never
touches nourishible's own compute.

This repo tracks the **current, latest version only** — no archived/legacy copies. History
lives in git; the working tree is always what you should install today.

## What's here

Two pieces, each doing one job:

- **[`skills/recipe-nourishible/`](./skills/recipe-nourishible)** — extraction. This is
  what runs *in your agent*: it watches a video or note (YouTube and Xiaohongshu/XHS
  directly; Instagram via local screen capture — see [`docs/capture/`](./docs/capture),
  macOS only), reads on-screen ingredients/steps, cross-references the transcript/caption,
  matches key moments to steps (e.g. "00:20 — add butter and stir"), and picks a good
  thumbnail. It has no idea what a nourishible account is — it just produces a structured
  recipe.
- **A hosted, remote MCP server** at `nourishible.com/mcp` — saving, under your account.
  This is the only thing that holds your login and writes to nourishible's database.
  Connecting it *is* the login: your agent pops your browser, you sign in and approve, and
  it's done — no separate CLI step, nothing to clone or run yourself. Read tools cover
  every user's public recipes; write tools are scoped to your own account.

[`SKILL.md`](./SKILL.md) at the repo root is a published, byte-identical copy of the
skill's instructions (`skills/recipe-nourishible/SKILL.md`), so an agent can fetch them
from `raw.githubusercontent.com/mag-dot/nourishible-mcp/main/SKILL.md` without cloning.
Edit the one inside the skill directory; `scripts/build-skill.sh` fails the build if the
two drift apart.

The skill calls the MCP server's tools to save what it extracted — it doesn't (and can't)
write to the database on its own. You need both connected for a recipe to actually land in
your library — but you don't have to set them up separately. Any agent can install both
in one pass by following [`INSTALL.md`](./INSTALL.md), and for Claude Code the whole repo
is packaged as a single plugin ([`.claude-plugin/`](./.claude-plugin),
[`.mcp.json`](./.mcp.json)) that does the same in one command — see Install below.

## Install

Both pieces go in together — you never have to install the skill and connect the MCP
server as two separate errands.

**Any agent — one step:** paste this into your agent (Claude Code, Claude Desktop, Cursor,
Codex CLI, …) and it does the whole setup itself:

```
Set up nourishible for me by reading and following
https://raw.githubusercontent.com/mag-dot/nourishible-mcp/main/INSTALL.md
```

[`INSTALL.md`](./INSTALL.md) is written for the agent rather than for you: it tells it to
install the skill *and* register the remote MCP server in the same pass, with the exact
locations and commands for the common agents. Where a step needs a GUI it can't drive
(Claude Desktop's connector settings, the claude.ai skill upload), it hands you that one
piece to click instead of silently skipping it.

**Claude Code — one command, if you'd rather not paste a prompt:** this repo is also a
Claude Code plugin bundling the skill *and* the MCP connection.

```
/plugin marketplace add mag-dot/nourishible-mcp
/plugin install nourishible@nourishible-mcp
```

Either way, the MCP connection is registered immediately, and the install itself finishes
the OAuth sign-in (your agent pops your browser, you approve) rather than leaving it for
later — that part can't be skipped, it's what ties the connection to *your* account.
Everything else — extraction, structuring, saving — just works after that.

Then paste a recipe video/note link and ask your agent to save it.

## License

MIT — except the video download/frame-extraction pipeline and the Instagram capture
pipeline, which carry their own attribution. See
[`skills/recipe-nourishible/SKILL.md`](./skills/recipe-nourishible/SKILL.md)'s Attribution
section.
