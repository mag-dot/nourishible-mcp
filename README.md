# nourishible-mcp

Extract recipes from any cooking video with your own AI agent — Claude Code, Claude
Desktop, Cursor, or any other MCP-capable coding agent — and save them straight to your
[nourishible](https://nourishible.com) library. Your agent does the work (download,
watch, structure the recipe), so it's free and uncapped: no extraction quota, because it
never touches nourishible's own compute.

**Status: early — this repo was just created.** The `skills/recipe-nourishible/` skill
(the actively maintained one) and a local MCP client fallback are being built now. In the
meantime, see [`archive/`](./archive) for the two skills this one is being built from —
not maintained, kept for provenance only, don't install them.

## What's coming

- `skills/recipe-nourishible/` — one self-contained skill: watches a video, reads
  on-screen ingredients/steps, cross-references the transcript and caption, matches key
  moments to steps (e.g. "00:20 — add butter and stir"), picks a good thumbnail, and
  saves the result to your nourishible account.
- A hosted, remote MCP server at nourishible.com — connecting it is the login (your agent
  pops your browser, you sign in and approve, done — no separate CLI step). Read tools
  cover every user's public recipes; write tools are scoped to your own account.
- `mcp/` — a local MCP client, kept here as a fallback for agents that don't yet support
  remote-MCP OAuth.

## License

MIT, except `archive/` — see that folder's own README for the original authorship/license
of what's archived there.
