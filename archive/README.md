# Archive

This folder is a historical record, not a maintained package. Nothing in this repo
installs, imports, or depends on anything under here.

## What's here and why

- **`watch/`** — the original `/watch` skill (video → frames + transcript), MIT-licensed,
  by [bradautomates](https://github.com/bradautomates/claude-video). `skills/recipe-nourishible/`
  (the live skill in this repo) vendors its own copy of `watch/scripts/*.py`, descended
  directly from this version — kept here verbatim, with its original license/author
  metadata in `watch/SKILL.md`'s frontmatter intact, as the recorded source.
- **`recipe-extract/`** — the original `/recipe-extract` skill, nourishible2's own
  reference implementation for turning watch's frames+transcript into a structured
  recipe. `skills/recipe-nourishible/` is the direct successor to this skill: same
  structuring/confidence/thumbnail-selection approach, merged with `watch/` into one
  self-contained package and pointed at nourishible's real MCP connector instead of a
  dev-only seed-script persistence step.

## Why archive instead of just deleting

These two skills used to live side by side in the private `nourishible-app` repo as
internal/dev tooling. `skills/recipe-nourishible/` replaces both of them there — but the
history of what it was built from is worth keeping on the record, not lost. If you're
looking for the actively maintained skill, use `../skills/recipe-nourishible/`, not
anything in this folder.
