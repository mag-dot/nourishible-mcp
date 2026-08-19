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

The skill calls the MCP server's tools to save what it extracted — it doesn't (and can't)
write to the database on its own. You need both connected for a recipe to actually land in
your library.

## Install

1. Install the skill for your agent (Claude Code: as a plugin, or copy
   `skills/recipe-nourishible/` into `~/.claude/skills/`; other harnesses have their own
   skill directory — see your agent's docs).
2. Connect nourishible: see `nourishible.com/mcp` for the exact command for your agent.
3. Paste a recipe video/note link and ask your agent to save it.

## License

MIT — except the video download/frame-extraction pipeline and the Instagram capture
pipeline, which carry their own attribution. See
[`skills/recipe-nourishible/SKILL.md`](./skills/recipe-nourishible/SKILL.md)'s Attribution
section.
