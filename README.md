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
your library. For Claude Code, this repo is packaged as a single plugin
([`.claude-plugin/`](./.claude-plugin), [`.mcp.json`](./.mcp.json)) so installing it sets
up both pieces together instead of two separate steps — see Install below.

## Install

**Claude Code — one step, both pieces:** this repo is a Claude Code plugin that bundles the
skill *and* the remote MCP connection together, so a single install sets up both instead of
doing them separately.

```
/plugin marketplace add mag-dot/nourishible-mcp
/plugin install nourishible@nourishible-mcp
```

The MCP connection is registered immediately; you still complete the OAuth sign-in (your
agent pops your browser, you approve) the first time it actually tries to save something —
that part can't be skipped, it's what ties the connection to *your* account. Everything
else — extraction, structuring, saving — just works after that.

**Any other MCP-capable agent** (Claude Desktop, Cursor, …): install the skill and connect
nourishible as two separate steps, since the plugin bundling above is Claude Code-specific.

1. Install the skill: copy `skills/recipe-nourishible/` into your agent's skill directory
   (see your agent's docs for where that is).
2. Connect nourishible: see `nourishible.com/mcp` for the exact command for your agent.
3. Paste a recipe video/note link and ask your agent to save it.

## License

MIT — except the video download/frame-extraction pipeline and the Instagram capture
pipeline, which carry their own attribution. See
[`skills/recipe-nourishible/SKILL.md`](./skills/recipe-nourishible/SKILL.md)'s Attribution
section.
