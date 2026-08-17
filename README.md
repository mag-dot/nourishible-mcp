# nourishible-mcp

Extract recipes from any cooking video with your own AI agent — Claude Code, Claude
Desktop, Cursor, or any other MCP-capable coding agent — and save them straight to your
[nourishible](https://nourishible.com) library. Your agent does the work (download, watch,
structure the recipe), so it's free and uncapped: no extraction quota, because it never
touches nourishible's own compute.

This repo tracks the **current, latest version only** — no archived/legacy copies. History
lives in git; the working tree is always what you should install today.

## What's here

- **[`skills/recipe-nourishible/`](./skills/recipe-nourishible)** — one self-contained
  skill: watches a video (YouTube directly; Instagram via local screen capture — see
  [`docs/capture/`](./docs/capture), macOS only), reads on-screen ingredients/steps,
  cross-references the transcript and caption, matches key moments to steps (e.g.
  "00:20 — add butter and stir"), picks a good thumbnail, and saves the result to your
  nourishible account.
- **A hosted, remote MCP server** at nourishible.com — connecting it is the login (your
  agent pops your browser, you sign in and approve, done — no separate CLI step). Read
  tools cover every user's public recipes; write tools are scoped to your own account. See
  `nourishible.com/mcp` for the connection URL and instructions.
- **[`mcp/`](./mcp)** — a local MCP client, kept here as a fallback for agents that don't
  yet support remote-MCP OAuth.

## Install

Install the skill for your agent (Claude Code: as a plugin, or copy
`skills/recipe-nourishible/` into `~/.claude/skills/`; other harnesses have their own skill
directory — see your agent's docs), then connect nourishible via the remote MCP server at
`nourishible.com/mcp`. Paste a recipe video link and ask your agent to save it.

## License

MIT — except the video download/frame-extraction pipeline and the Instagram capture
pipeline, which carry their own attribution. See
[`skills/recipe-nourishible/SKILL.md`](./skills/recipe-nourishible/SKILL.md)'s Attribution
section.
