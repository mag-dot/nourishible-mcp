# Instagram capture — the rule that governs it

`CONTRACT.md` in this folder is the one binding rule behind why
`skills/recipe-nourishible/scripts/capture/` records the screen instead of fetching from
Instagram: **content enters only because a human caused it to play.** Read it before
changing anything about how this skill acquires Instagram content — it is not background
reading, it is the constraint the whole capture design exists to satisfy.

**Carousels, and where the line actually falls.** `capture-carousel.sh` handles
multi-image `/p/` posts, and it does advance the slides itself by clicking the post's own
"Next" control. That is inside the rule, not an exception to it: the contract's stated
test is *"who initiated the request to Meta's servers"*, and advancing a slide initiates
none — the user opened the post, Instagram has already delivered and preloaded the slides
into the page, and Next renders what the browser is holding in memory. The prohibited row
it superficially resembles, *"scripting the play button on a page a script opened"*,
describes a script driving a whole session unattended: opening URLs, logging in, walking a
list. Advancing a post a human opened and is sitting in front of is a different act.

What stays prohibited for carousels, and is deliberately not implemented: opening the post
URL ourselves, logging in, batch-walking a list of posts, and reading the slide image URLs
out of the DOM to download them (an automated fetch to Meta's CDN — the same category as
hotlinking). If you are extending this, that boundary is the thing to preserve.

This capture pipeline (and this rule) originated in `ig-saved`, an earlier project, and
was carried forward here alongside `skills/recipe-nourishible/`. The fuller governance
set that project produced — research notes on what Meta's APIs expose, the macOS
toolchain setup, and an unrelated infant-food safety rule set for a different (private,
backend-side) extraction pipeline — lives in nourishible's private repository, not here;
this public skill only needs the acquisition rule itself.

**yt-dlp against Instagram is confirmed broken, not just discouraged on terms grounds**:
tested 15 Aug 2026 against a valid, logged-in session across current stable, nightly, and
TLS-impersonated builds — HTTP 400 every time. Don't try cookie auth for Instagram in this
skill; `SKILL.md`'s Step 1 goes straight to capture.
