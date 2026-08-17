# Instagram capture — the rule that governs it

`CONTRACT.md` in this folder is the one binding rule behind why
`skills/recipe-nourishible/scripts/capture/` records the screen instead of fetching from
Instagram: **content enters only because a human caused it to play.** Read it before
changing anything about how this skill acquires Instagram content — it is not background
reading, it is the constraint the whole capture design exists to satisfy.

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
