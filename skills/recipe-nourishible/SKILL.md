---
name: recipe-nourishible
version: "1.5.1"
description: Turn a recipe video or post (Instagram Reel, YouTube Short/video, Xiaohongshu/XHS/RED note) into a structured recipe and save it to nourishible. Uses bundled local MCP extraction tools when available, with bundled scripts as a compatibility fallback, then saves through the hosted Nourishible MCP server.
argument-hint: "<video-url>"
allowed-tools: Bash, Read, AskUserQuestion
homepage: https://github.com/mag-dot/nourishible-mcp
repository: https://github.com/mag-dot/nourishible-mcp
author: nourishible
license: MIT
user-invocable: true
---

# /recipe-nourishible

You don't have a video or recipe-structuring input; this skill gives you both. A bundled
Python script downloads the video, extracts frames, and gets a timestamped transcript
(native captions, or Whisper as a fallback). You then read the frames directly (you can
already read images — no separate OCR call), cross-reference them with the transcript and
caption, and write a structured recipe: ingredients, numbered steps each matched to the
moment in the video it happens at, a picked thumbnail, and confidence notes on anything
uncertain. The result saves straight into the user's real nourishible library through a
hosted MCP connector — connecting it is the only setup step, there's no separate login
command and nothing to build.

This skill is self-contained: the download/frame/transcript/capture scripts under
`scripts/` are bundled here directly, not a dependency on a separate skill. It descends
from earlier, narrower work (general-purpose video Q&A, an internal recipe-structuring
skill, and a retired Instagram screen-capture tool) — see the Attribution section at the
bottom for the credit that history is owed.

## MCP-first execution

If `recipe_setup_status`, `extract_recipe_evidence`, and
`instagram_capture_instructions` are callable, use them instead of invoking the matching
setup/watch scripts directly. The local MCP package carries this workflow as the
`nourishible://recipe-workflow` resource and bundles the scripts in its installed wheel.
Continue to use the hosted Nourishible tools for deduplication, saving, and thumbnail
upload; OAuth credentials never enter the local extraction server.

If those local tools are absent, follow the script commands below. This keeps manual
skill installs and agents without local MCP support working.

## Resolve `SKILL_DIR` (do this before any command)

Set `SKILL_DIR` to the absolute path of the directory containing **this** SKILL.md you
just Read — your harness told you that path in the Read result. The bundled script is
always a direct sibling of this file, in every install layout (a Claude Code plugin, a
manual clone, `~/.claude/skills/`, `~/.codex/skills/`, …):

```bash
SKILL_DIR="<absolute path of the directory containing the SKILL.md you Read>"
WATCH_SCRIPT="$SKILL_DIR/scripts/watch.py"
FRAMES_SCRIPT="$SKILL_DIR/scripts/frames.py"   # used directly by Step 5.5's thumbnail re-grab
if [ ! -f "$WATCH_SCRIPT" ]; then
  echo "ERROR: could not find $WATCH_SCRIPT — is scripts/ present as a sibling of this SKILL.md?" >&2
  exit 1
fi
```

Substitute that literal path for `${SKILL_DIR}` in every command below. This works on
every harness that can run bash and read local image files (Claude Code, Claude Desktop
with a local MCP client, Cursor agent mode, Codex CLI, Gemini CLI, …) without relying on
any harness-specific environment variable.

### Reference files

Platform-specific procedure and audit material live in `${SKILL_DIR}/references/` rather
than in this file, so a run only pays for the path it actually takes. `Read` the one your
URL routes to, when you get there — not upfront:

| File | Read it when |
|---|---|
| `references/instagram.md` | the URL is instagram.com (either capture route, and carousels) |
| `references/xiaohongshu.md` | the URL is xiaohongshu.com or xhslink.cn |
| `references/security.md` | auditing what the skill does to the machine; a user asks about permissions |
| `references/attribution.md` | credit/licence questions about where this skill came from |

If you fetched this SKILL.md standalone over HTTP (from
`raw.githubusercontent.com/mag-dot/nourishible-mcp/main/SKILL.md`) rather than from an
installed skill directory, there is no local `${SKILL_DIR}` — fetch the reference you need
from `.../main/skills/recipe-nourishible/references/<name>.md` instead.

## Step 0 — Setup preflight (runs every invocation, silent on success)

This covers the YouTube path (ffmpeg/yt-dlp/Whisper) — every invocation needs it. The
Instagram path has its own, separate, opt-in preflight (`--check-capture`/
`--install-capture`) covered in Step 1 below; don't run it here, only when the video is
actually an Instagram URL — a YouTube-only user should never be asked to install any of
the Instagram-specific tooling.

**Python interpreter:** every `python3 ...` command in this skill is for macOS/Linux. On
**Windows**, substitute `python` — the `python3` command on Windows is the Microsoft Store
stub and will not run the script.

On the first invocation in a session, use structured preflight so you can detect first-run
setup:

```bash
python3 "${SKILL_DIR}/scripts/setup.py" --json
```

Branch on two fields:

- **`can_proceed: true` and `first_run: false`** → setup is already done (the user may have
  deliberately skipped a Whisper key — that's allowed). Proceed to Step 0.5 without comment.
- **`first_run: true`** → genuine first-time setup. Do these in order:
  1. If `missing_binaries` is non-empty, run the installer first (it auto-installs on macOS
     / prints commands elsewhere — see below) and confirm the binaries land. **Do not skip
     this and jump to preferences.**
  2. Run the installer once more if needed so it scaffolds `~/.config/watch/.env` (it only
     writes the template when the file is absent, so let it create the file *before* you
     write any values into it). This path name is inherited from the vendored script — see
     Attribution — not a typo; it's an internal config location, not user-facing.
  3. Write the tested defaults below into `~/.config/watch/.env` and set
     `SETUP_COMPLETE=true`. No questions — see "First-run defaults" below.
- **`can_proceed: false` and `first_run: false`** → setup was finished before but the
  environment regressed (e.g. `missing_binaries` after an OS change). Run the installer to
  remediate, then proceed. Don't re-ask preferences.

A missing Whisper key is *fine, not a blocker*: on a genuine first run `status` will read
`needs_key` even when binaries are present — that's expected, not something to fix or ask
about (see below).

On follow-up invocations in the same session, use the silent check:

```bash
python3 "${SKILL_DIR}/scripts/setup.py" --check
```

This is a <100ms lookup. Exit 0 means the skill can run — this **includes a user who
finished setup without a Whisper key** (keyless is allowed). On exit 0 the script emits
**nothing** — proceed without comment. **Do NOT announce "setup is complete."**

On non-zero exit, follow the table:

| Exit | Meaning | Action |
|------|---------|--------|
| `2` | Missing binaries (`ffmpeg` / `ffprobe` / `yt-dlp`) | Run installer |
| `3` | Genuine first run with no Whisper API key | Run installer to scaffold `.env`, write the defaults below, proceed with `--no-whisper` |
| `4` | Both missing | Run installer, write the defaults below, proceed with `--no-whisper` |

The installer is idempotent — safe to re-run:

```bash
python3 "${SKILL_DIR}/scripts/setup.py"
```

On macOS with Homebrew, it auto-installs `ffmpeg` and `yt-dlp`. On Linux/Windows, it prints
the exact install commands for the user to run. It scaffolds `~/.config/watch/.env` with
commented placeholders and default settings at `0600` perms.

### First-run defaults (no questions asked)

Both preferences below are tested defaults, not things to ask the user about — first-run
setup should complete with zero `AskUserQuestion` calls.

**API key:** if one is still missing after install, don't ask. Proceed with `--no-whisper`
silently (videos without native captions come back frames-only). A user who wants Whisper
can add `GROQ_API_KEY=...` (preferred — cheaper, faster) or `OPENAI_API_KEY=...` to
`~/.config/watch/.env` themselves at any time.

**Detail:** write the default directly into `~/.config/watch/.env` on its own line, **no
trailing inline comment**:

```bash
WATCH_DETAIL=balanced
```

(`balanced` — scene-aware frames, cap 100 — is the right starting point for most recipe
Shorts; see the `--detail` flag docs below if a user later wants to change it by hand.)

Once dependencies are confirmed and the line above is written, write or update
`SETUP_COMPLETE=true` in the same file. Don't revisit either default once it's set.

## When to use

- User pastes an Instagram Reel, YouTube Short/video, or Xiaohongshu (XHS/RED/小红书) note
  link and asks to save/extract it as a recipe, or types `/recipe-nourishible <url>`.
- User pastes an Instagram **carousel** (`/p/…`, often with `?img_index=N`) whose recipe is
  written on the images themselves. A carousel may hold several separate recipes, one per
  slide — see `references/instagram.md`.
- User asks "what's the recipe in this video/post" for something that is clearly a
  cooking/recipe video or note.

Not for: general video Q&A unrelated to recipes, blog/website recipe scraping (out of
scope — no download step applies), TikTok (not supported by the bundled download script).

**Route by platform in Step 1.** YouTube and Xiaohongshu work everywhere this skill runs
and go through `watch.py`. Instagram never goes through `watch.py`: it is read from a
rendered page, by one of three routes — read `references/instagram.md` when you get there,
and don't rule Instagram out based on the OS your own shell reports.

## Step 0.5 — dedup check (do this before spending any download/frame budget)

Before calling the bundled script, check whether this exact video has already been saved
by this user. **Normalize both the incoming URL and every already-saved `sourceUrl` before
comparing** — a raw string/exact match misses real duplicates: YouTube URLs routinely carry
a tracking `&pp=...`/`&si=...`/`&t=...` param that has nothing to do with video identity.
Extract just the video id (the `v=` param, or the path segment after `youtu.be/` /
`shorts/`) from both sides and compare on that. For a Xiaohongshu link, resolve a
`xhslink.cn` short link to its canonical `xiaohongshu.com/discovery/item/<id>` or
`/explore/<id>` form first (Step 1's Xiaohongshu section does this for you as a side
effect of probing the note) and compare on that hex note id — the short link itself
carries a rotating `xsec_token`/`share_id` that has nothing to do with note identity and
will never match a previously-saved `sourceUrl` even for the exact same note.

Call `list_my_recipes` (no query needed, or narrow with a title guess if the library is
large) and scan the returned `sourceUrl` values yourself for a matching normalized video
id — this is a normal in-context text comparison over a JSON list you already have, not a
database query. (Use `list_my_recipes`, not `search_recipes` — the latter is public across
every nourishible user's library and doesn't tell you which results are yours, so it can't
answer "have I already saved this.")

If a recipe for that video id already exists:

- Tell the user it's already saved (title + link to it in the app), and ask whether they
  want to re-extract anyway (e.g. the video changed, or the first extraction was poor) —
  don't silently skip, and don't silently re-run and create a duplicate.
- If they confirm a re-extract, call `update_recipe` on the existing one instead of
  `save_recipe` — a delete+recreate loses the recipe's id/slug/share link.

Re-run this check once more immediately before the actual save (Step 6.5) — protects
against a race with anything else that wrote to this account since you first checked.

## Step 0.6 — is this actually a recipe? (reject non-food content early)

Skim the video title, description, and (if quick to get) the first bit of transcript
*before* doing the full frame-extraction pass. Reject and stop, telling the user plainly
why, if:

- The content isn't food/cooking at all (vlogs, hauls, unrelated tutorials, music videos
  that happen to be tagged with a food emoji, etc.).
- It's food-adjacent but not a recipe someone could cook from (a restaurant review, a
  mukbang/eating video with no preparation shown, a "what I eat in a day" montage with no
  method) — these have no ingredients/steps to extract.
- It's an ad/sponsored placement with no actual recipe content, just a product pitch.

A genuine recipe video needs at least one of: a stated or shown ingredient list, or a
sequence of preparation steps (chopping, mixing, cooking, assembling) that a viewer could
follow. If you're not sure after the title/description/opening transcript, it's fine to do
Step 1 and decide from the fuller evidence — but don't structure a fake recipe out of a
video that's clearly not one just because a URL was given to you.

## Step 1 — fetch frames + transcript

**The path here depends on the platform.** YouTube downloads normally. Instagram does
**not** — cookie auth (`--cookies-from-browser`) is not a working fallback for Instagram:
yt-dlp's Instagram extractor returns HTTP 400 even with a valid, logged-in session, tested
across current stable/nightly/TLS-impersonated builds (verified 15 Aug 2026). Don't try
cookie auth for Instagram, and don't retry it hoping for a different result — go straight
to local capture below.

### YouTube

```bash
python3 "$WATCH_SCRIPT" "<video-url>" --detail balanced --resolution 1024 --out-dir "${OUT_DIR:-}"
```

Notes on the flags, and why they differ from this script's own defaults:

- `--resolution 1024` (not the default 512) — recipe frames frequently carry small
  on-screen text (ingredient callouts, timers, quantity overlays) that needs to be
  legible, not just recognizable. This is a *width* ceiling; the real cost governor is the
  0.8 MP area cap in `frames.py`, which holds every frame to ~800-1070 image tokens
  whatever its orientation. So this flag buys legibility on landscape sources and costs
  little — it does not multiply your frame budget.
- `--detail balanced` is the right starting point for essentially everything, Shorts and
  long-format alike. **For a longer video, narrow the range — do not raise the detail.**
  Screen with a transcript pass and pass `--section` (below), or focus with
  `--start`/`--end` around the actual cooking steps. `--detail token-burner` is
  **uncapped** — it keeps every scene-change frame across the whole video, which on a long
  source is hundreds of frames and tens of thousands of wasted image tokens for content
  that is mostly intro, sponsor read and outro. Reach for it only on a short clip whose
  every cut genuinely matters.
- If the video is bot-gated ("Sign in to confirm you're not a bot"), set
  `WATCH_COOKIES_FROM_BROWSER` (or pass `--cookies-from-browser BROWSER`) — this genuinely
  is a cookie-auth problem, unlike Instagram's.
- Pass `--out DIR` through as `--out-dir` if the user (or your caller) specified one;
  otherwise let it use the default tmp dir.

**Screen before downloading (anything over ~3 minutes, or whenever the source looks like a
long-format video rather than a Short/Reel):** downloading and decoding a 20-minute video to
extract 90 seconds of actual recipe is wasted time on every run. Do a transcript-only pass
first — no video bytes move:

```bash
python3 "$WATCH_SCRIPT" "<video-url>" --detail transcript --out-dir "${OUT_DIR:-}"
```

Read the returned transcript and find where the recipe content actually starts and ends —
past the cold open/sponsor read/"welcome back to the channel" preamble, and before any
outro/subscribe plea/next-video teaser. Then re-run pointed at that range, which downloads
**only that slice** (not "downloads everything, then only looks at that slice" — this is a
`yt-dlp --download-sections` cut, so the wasted bytes are never fetched):

```bash
python3 "$WATCH_SCRIPT" "<video-url>" --detail balanced --resolution 1024 --section "START-END" --out-dir "${OUT_DIR:-}"
```

`--section` takes the same `SS`/`MM:SS`/`HH:MM:SS` formats as `--start`/`--end` but controls
what gets *downloaded*, not just what gets sampled into frames — pass both together when the
recipe segment itself still has slow stretches you want denser/sparser sampling within
(`--start`/`--end` after the fact still work normally on the now-shorter local file). If the
transcript pass comes back empty (no captions, auto-captions disabled) or the source isn't a
`yt-dlp`-backed URL at all (Instagram, XHS), skip straight to the normal full download below
— there's nothing to screen against. Don't guess a section from the title/thumbnail alone;
screen from the transcript or don't screen at all — a wrong guess that clips out the actual
recipe steps is worse than the wasted download time this step exists to save.

**Set the frame budget from the text you already have.** The transcript-only pass above
costs nothing and is not just a range-finder — read the transcript *and* the description
alongside it before committing to a frame density. A large share of YouTube recipe
descriptions (and almost every Instagram/XHS caption) carry the complete quantified
ingredient list as plain text. When they do, frames are there to *confirm* the list and to
time the steps, not to discover the recipe, and you do not need 50-80 of them to do that:

- **Description/caption already has a complete quantified ingredient list** → run
  `--detail efficient` (cap 50, keyframes) instead of `balanced`, and lean on the
  transcript-cue pass below for step timing. Typically halves the frame spend with nothing
  lost, because the thing frames would have been discovering is already in hand.
- **Partial list** (ingredients named but no quantities, or steps only) → stay on
  `balanced`. The frames are carrying real information.
- **No usable text at all** (no captions, no description, silent video) → stay on
  `balanced`, and expect the on-screen text to be the whole recipe.

Decide this from the text, never from the video's length or your guess at its format. If
Step 3 then comes up short on a specific ingredient or quantity, add frames with
`--timestamps` for exactly those moments rather than re-running the whole pass at a higher
detail — a targeted re-grab costs a few frames, a re-run costs all of them again.

**Transcript-cue pass (do this for every recipe, not just when sparse):** after the first
run, scan the transcript for the moments a cook narrates quantities/technique ("add two
tablespoons of...", "let that go for five minutes", "fold in the..."), and for moments a
cook typically *acts* even without narrating it clearly (a cut to a sizzling pan, a bowl
being combined). Re-run once with `--timestamps` pinned to those moments (see "Transcript-
cue frames" below), pointed at the already-downloaded local file so it doesn't re-download.
This pass is what Step 3.5 (matching steps to video moments) depends on — a quantity or
action is often only correct/visible at one specific frame, not "somewhere in this scene."

**Other useful `watch.py` flags:**

- `--section START-END` — download only this range from the source (see "Screen before
  downloading" above). Changes what gets fetched; `--start`/`--end` below only change what
  gets sampled from whatever local file already exists.
- `--start T` / `--end T` — focus on a section. Accepts `SS`, `MM:SS`, or `HH:MM:SS`. When
  either is set, fps auto-scales denser.
- `--timestamps T1,T2,…` — grab a frame at each of these absolute timestamps. Use this
  after reading the transcript to capture moments visual selection alone might miss.
- `--max-frames N` — override the preset cap for a tighter token budget.
- `--fps F` — override auto-fps (clamped to 2 fps max).
- `--out-dir DIR` — keep working files somewhere specific (default: an auto-generated tmp dir).
- `--whisper groq|openai` — force a specific Whisper backend (default: prefer Groq if both
  keys exist).
- `--no-whisper` — disable the Whisper fallback entirely (frames-only if no captions).
- `--no-dedup` — keep near-duplicate frames (by default, visually near-identical frames to
  the previous kept one are dropped so the frame budget goes to distinct content).

### Instagram

**Never `yt-dlp`, never `watch.py`.** It returns HTTP 400 on Instagram even with a valid
logged-in session, and the acquisition contract forbids it anyway; cookie auth is not a
fallback. Content is read from a rendered page, by one of three routes:

- **Signed-out agent browser** — you open the one post in a browser you control that is
  confirmed signed out of Instagram (on a local Claude desktop session: the built-in
  Browser pane). Caption from `og:description`, native-resolution frames drawn from the
  `<video>` element. Needs nothing from the user and is usually the fastest; **no audio
  transcript**. Try this first when such a browser exists.
- **Local screen capture** — higher fidelity (sampled frames, on-device Vision OCR, a
  Whisper transcript). Needs macOS, Screen Recording permission for the shell running the
  scripts, and Chrome on the same machine.
- **Agent-controlled browser** — the user's own Chrome, usually signed in: the user opens
  and plays, you only record. Works from any platform, including a remote Linux container
  driving a macOS Chrome through a browser extension. **No audio transcript**.

Don't conclude "Instagram is macOS-only" because *your own* shell reports Linux.

**Read `${SKILL_DIR}/references/instagram.md` before running any of them.** It carries the
step-by-step procedure for each route (including how to get the thumbnail frame onto disk
from the signed-out browser), the dead ends to skip on a local desktop session, the
carousel path (a `/p/` post whose recipe is written on the slides), the acquisition rule,
and the per-path failure modes.

**The acquisition rule, in short, because it is not negotiable:** in a **signed-out**
browser you may open only the one post the user asked for, at most twice, and never click
Meta's popups closed or download the video. In a **signed-in** browser the user opens and
plays the post and you only record what is on their screen — never navigate there. Never
walk a list of posts in either. See
[`docs/capture/CONTRACT.md`](../../docs/capture/CONTRACT.md).

### Xiaohongshu (XHS/RED/小红书)

Works on every platform, no browser or screen capture involved — `yt-dlp` ships a real
`XiaoHongShu` extractor, so this goes through `watch.py` the same way YouTube does:

```bash
python3 "$WATCH_SCRIPT" "<xiaohongshu-or-xhslink-url>" --detail balanced --resolution 1024 --out-dir "${OUT_DIR:-}"
```

**A large share of XHS recipe content is a photo/图文 note, not a video** — images plus a
text description, no video or audio. `watch.py` probes and branches automatically, and the
two shapes produce differently-shaped reports: a photo note has no transcript and every
step's `timestampSeconds` is `null` (not an evidence gap to chase), and its description is
the caption-text equivalent of Instagram's `caption.txt`.

**Read `${SKILL_DIR}/references/xiaohongshu.md` before structuring one** — it covers both
note types, the `xsec_token` short-link handling that Step 0.5's dedup depends on, and the
tested limits.

### Focusing on a section (higher frame rate)

When the user asks about a specific moment, or the video is long with a slow intro, pass
`--start`/`--end` — denser sampling than a full-video scan, still capped at 2 fps and
bounded by the detail-mode cap. Transcript is auto-filtered to the same range. Frame
timestamps are always absolute (real video timeline, not offset-from-start).

### Transcript-cue frames

`--timestamps` forces a frame at exact moments you choose by reading the transcript first
— scene/keyframe selection can miss a presenter pointing at something ("look here", "as you
can see") since pointing at a slide is often a *low* visual-change moment. Cue frames are
additive (merged with whatever `--detail` already selected) and pinned first (reserved
against the frame cap before the detail engine runs, so they're never evicted).

## Step 2 — read everything

`Read` every frame path the script printed, in one batch (parallel tool calls). You now
have three evidence streams to reconcile:

1. **Frames** — what's visually on screen, including any on-screen text overlays
   (ingredient lists, quantities, step callouts, timers). Read the overlay text directly
   off the image — don't guess if it's legible.
2. **Transcript** — what's spoken, with timestamps (`captions` = native, `whisper (...)` =
   transcribed — the report header says which).
3. **Caption/description text** — if the source is Instagram, `caption.txt` from the
   capture directory very often contains the full ingredient list as plain text, sometimes
   *more* complete than what's shown on screen or said aloud. Treat it as a first-class
   source, not an afterthought.

## Step 3 — structure the recipe

Produce a recipe JSON matching this schema exactly:

```json
{
  "title": "string",
  "sourceUrl": "string (the resolved canonical URL — see Step 1's Xiaohongshu note on short links)",
  "sourcePlatform": "instagram | youtube | xiaohongshu",
  "creatorHandle": "string",
  "thumbnailFramePath": "path to the full-resolution `thumb_*.jpg` re-grab of your #1 pick (Step 5.5 — rank on the frames you already extracted, then re-grab that timestamp; not a new download)",
  "servings": "integer, best estimate if unstated (say so in confidence notes)",
  "totalTimeMinutes": "integer or null",
  "ingredients": [
    {
      "rawText": "the original line as seen/heard, verbatim",
      "quantity": "number or null (null for 'to taste')",
      "unit": "string or null, normalized (tbsp, tsp, g, cup, ml, oz, clove, pinch, ...)",
      "name": "string",
      "optional": "boolean",
      "category": "produce | protein | dairy | pantry | other, or null"
    }
  ],
  "steps": [
    { "text": "string, one clear instruction per step", "timestampSeconds": "number or null — see Step 3.5" }
  ],
  "tags": ["cuisine/meal-type/dietary tags you can confidently infer — don't force it"],
  "notes": "string or null — anything worth flagging that doesn't fit elsewhere",
  "confidence": {
    "<field path, e.g. 'ingredients[2].quantity'>": "high | medium | low"
  }
}
```

Structuring rules:

- **Reconcile, don't just concatenate.** When caption text, on-screen text, and spoken
  audio disagree on a quantity or ingredient, prefer on-screen text > caption text >
  spoken audio, in that order — but only when they actually disagree. Note the conflict in
  `notes` or a low confidence flag either way.
- **One ingredient per line.** Split combined lines ("salt and pepper to taste" → two
  ingredient entries) so each is independently taggable/scalable.
- **Normalize units** to a small controlled vocabulary (tbsp, tsp, cup, g, kg, ml, l, oz,
  lb, clove, pinch, can, bunch) rather than preserving every raw spelling — keep the
  original in `rawText` regardless.
- **Steps should be actions, not narration.** Compress "so what I'm gonna do now is just
  go ahead and add in about a cup of..." into "Add 1 cup of...". Keep the count of steps
  close to what a person would actually check off while cooking (typically 4-10 for a
  Reel-length recipe) — don't over-split.
- **Servings/time**: if genuinely unstated anywhere, give your best estimate from the
  ingredient quantities/format shown and mark it `low` confidence rather than leaving it
  null — the app needs a starting number to scale from.

## Step 3.5 — match key moments to steps

**Skip this step entirely for a Xiaohongshu photo/图文 note** — there's no video timeline
to match against, so every step's `timestampSeconds` is simply `null`. That's not a gap to
fill; go straight to Step 4.

This is the step that makes a saved recipe's video timestamps actually useful (e.g. a step
that reads "00:20 — add butter and stir"), not an occasional side effect of extraction.
Do this deliberately for every step, not opportunistically for whichever ones happen to
line up:

1. For each step, ask: is there a specific moment in the video — a frame, or a spoken
   line with a timestamp — that shows or states this exact action happening? Use the
   Step 1 transcript-cue pass and the frame timestamps you already have.
2. If yes, set `timestampSeconds` to that moment (prefer the moment the *action starts*,
   e.g. when the ingredient hits the pan, not when the presenter starts narrating the next
   step). Round to the nearest second.
3. If a step genuinely has no single attributable moment — a summary step ("plate and
   serve"), an instruction stated once at the start covering the whole video ("preheat the
   oven to 400°F"), or a step your evidence just doesn't pin down confidently — leave
   `timestampSeconds: null`. **Do not guess a plausible-sounding number** — a wrong
   timestamp is worse than none, since it actively misleads someone using it to jump to
   that part of the video.
4. If you're not fully confident in a timestamp you did set (e.g. it's the right general
   area but you can't be sure it's the exact second), add it to `confidence` at
   `steps[N].timestampSeconds` as `medium` or `low`, same discipline as Step 4 below — a
   timestamp isn't exempt from the same honesty the rest of the recipe gets.

A well-matched recipe usually has a timestamp on most "doing" steps (add, mix, cook, fold,
flip, remove) and `null` on framing/summary steps — not 100% coverage, and not 0%.

## Step 4 — confidence scoring

For every field you're not fully certain of, add an entry to `confidence`. Use this as the
actual criteria, not a vibe:

- **high** — stated identically (or compatibly) in at least two of {on-screen text,
  caption, audio}, or stated unambiguously in one source with no conflicting signal from
  the others.
- **medium** — stated clearly in exactly one source, with the others silent (not
  conflicting) on that field.
- **low** — sources disagree, the source was ambiguous/partially obscured, or you're
  estimating/inferring (e.g. servings backed out from ingredient quantities, a step
  timestamp you're not sure aligns).

Don't add high-confidence fields to the map at all — only flag what a reviewer should
actually look at. A recipe where nothing needs a second look should have a small or empty
`confidence` object, not one entry per field.

## Step 5 — refinement suggestions

Separately from the JSON (this is for the human, not part of the saved record), write a
short **"Worth double-checking"** list: 2-6 bullets, each naming a specific field and why —
the same signal `confidence` carries, phrased as something a reviewer can act on in a few
seconds. Examples of the right level of specificity:

- "Soy sauce quantity (2 tbsp) — only heard on audio, not shown or captioned; the pour
  looked closer to 3 tbsp on screen."
- "Step 4 timing (5 minutes) — caption says 'simmer until reduced', audio says '5 minutes',
  used the audio number but reduction time varies more than that suggests."
- "Servings (4) — never stated anywhere, backed out from a family-size portion shown at the
  end; treat as a rough estimate."

Skip this list entirely (say so plainly) if the extraction was clean and nothing scored
`low`/ambiguous — don't manufacture concerns to fill space.

## Step 5.5 — pick the best 3 frames for preview thumbnails

Rank three, not one: #1 becomes the recipe's thumbnail and #2/#3 upload as candidates,
which nourishible keeps as a 60-day reviewable backup so a bad #1 can be swapped during
review without re-extracting. From the frames you already read in Step 2, pick the 3
strongest candidates using these criteria, in order:

1. **Finished-dish shot** — the plated/finished result, well-lit, food filling most of the
   frame, no hands/utensils obscuring it. This is always candidate #1 if one exists. A
   minor caption or watermark in a corner/margin doesn't disqualify a frame — a full,
   unobstructed view of the dish beats losing the shot entirely over small on-screen text.
2. **A striking mid-process shot** — a visually distinct cooking moment (a sizzling pan, a
   sauce being poured, a key ingredient close-up) that would read well as a card image even
   out of context.
3. **A second angle of the finished dish, or the best remaining candidate** — prefer
   variety (don't pick three near-duplicate frames of the same moment).

Reject frames that are: blurry/motion-blurred, mostly a person's face/torso with no food
visible, dominated by a hand/utensil obscuring the food, transition frames (mid-cut,
part-black), or carrying a caption/banner graphic — even one that doesn't sit directly over
the food — that spans roughly a third or more of the frame height. "Minor" in the rule above
means a short line along one edge, not a headline-sized banner across the top of the shot;
if you're checking whether a candidate qualifies as "minor," it doesn't.

**Confirm the frame is actually this dish before ranking it #1.** Scene-change and
keyframe candidates are pulled from the whole video indiscriminately, including any
recap/"coming up" montage, sponsor segment, or outro reel that shows *other* food from the
same channel. A finished-dish shot that looks great in isolation is still a wrong pick if
it isn't the dish these ingredients and steps produce — cross-check candidate #1 against
your own ingredients list (does the shape/color/components on screen match what Step 3
actually said this recipe contains?) before recording it, and drop straight to the next
candidate if it doesn't.

### Rank on the reading frames, upload a fresh full-resolution grab

**Never upload a reading frame directly.** The frames you read in Step 2 are deliberately
downscaled — 1024px wide at JPEG `-q:v 4` — because token cost scales with pixels. That is
the right size to *judge* composition and the wrong size to *be* the card image: it is the
full-size card/OG thumbnail everyone sees, and a 1024px `-q:v 4` frame lands on it visibly
soft. Rank on the reading frames, then re-grab your #1 pick's **timestamp** from the video
at full resolution:

```bash
python3 "$FRAMES_SCRIPT" "$VIDEO_PATH" "$OUT_DIR" --thumbnail-at "MM:SS"
```

`$VIDEO_PATH` is the local file Step 1 already downloaded (`watch.py` reports it, in the
`--out-dir` it names) — this re-reads that file, it does not re-download. Each frame in
Step 1's output carries its `timestamp_seconds` — that's the value to pass.
This writes `thumb_0000.jpg` at the source's native resolution (capped at 1440px wide /
1998px tall, never upscaled) at `-q:v 2`, using the same accurate two-stage seek as every
other timestamp grab, so it won't reproduce the ghosted-frame bug a fast/naive seek can
cause. It writes under its own `thumb_` prefix, so it leaves your reading and cue frames
alone. On a 1080×1920 reel that's a native 1080×1920 grab — roughly ten times the real
detail of the reading frame you ranked. **This grab, not the reading frame, is what Step 6.5
encodes and uploads.**

**If none of the frames you read is a clean finished-dish shot, search the full timeline
before settling.** The reading pass samples perhaps 80 frames; the video has thousands, and
the plated shot is often a brief held moment between two of them. This costs no image
tokens — it scores frames with ffmpeg locally:

```bash
python3 "$FRAMES_SCRIPT" "$VIDEO_PATH" "$OUT_DIR" --rank-candidates
```

It returns up to 12 timestamps: the sharpest correctly-exposed frame in each slice of the
timeline, each with a `sharpness` score from 0 to 1 (1 = the sharpest frame in this video).
On a 6-minute video it scores 353 frames in about 6 seconds. Then grab that shortlist in
**one** call and read it:

```bash
python3 "$FRAMES_SCRIPT" "$VIDEO_PATH" "$OUT_DIR" --timestamps "12.0,31.5,48.0,77.2"
```

This writes `cand_*.jpg` at 384px wide — about 350 image tokens each, so a 12-frame
shortlist costs roughly 4.2k. That is enough to judge composition and pick the finished
dish; it is deliberately far below the reading resolution, because your #1 pick gets
re-grabbed at full resolution with `--thumbnail-at` afterwards anyway.

**Use `--timestamps`, not a loop of `--thumbnail-at` calls.** `--thumbnail-at` clears its
own `thumb_*.jpg` prefix on entry, so calling it once per candidate leaves you with only
the last one — while reporting a successful path each time. It also grabs at full
thumbnail resolution (~2.8k tokens a frame on a 1080x1920 reel), so a 12-candidate loop
would cost ~33k tokens to end up with a single file.

**Prefer a candidate with high `sharpness`**: a frame at 0.5 is only middling for its own
video and will look soft as a full-size card, even if the composition is good.

**Blur disqualifies a frame here and nowhere else.** A motion-blurred frame — hands pouring,
stirring, adding — is often the *most* informative one for the recipe itself, so the reading
pass keeps it and Step 3.5 may well timestamp a step from it. It just can't be a card image,
so the candidate pool excludes it: stretches of video with nothing sharp in them are dropped
outright rather than contributing their least-bad frame. Don't apply this gate in reverse and
discard blurry frames as evidence.

**Read the shortlist; do not trust its order.** These are frames worth *looking at*, not a
ranked pick, and the tool says so in its own output. Pixel statistics cannot tell a finished
dish from raw ingredients: measured on a real recipe video, the raw tray scored *higher* on
both sharpness and saturation than the plated result, because uncooked food is uniformly
vivid while a cooked dish is browner and softer. A ranker built on those signals picks
confidently wrong. Only you can tell which frame is the finished dish.

Useful flags: `--candidates N` for a longer or shorter shortlist, `--rank-fps F` to sample
denser than 1/sec, `--start`/`--end` to search one region (timestamps come back absolute
either way), and `--candidate-resolution W` on the `--timestamps` grab if 384px isn't
enough to judge a particular video. Expect fewer candidates back than you asked for — a
slice whose sharpest frame is still soft is dropped rather than spending a slot on the
least-bad frame of a blurry stretch.

**Manual override:** the same command is how you override the ranking outright — if the
auto-picked #1 is wrong, or the caller told you which moment to use, pass that timestamp
instead and treat the result as your #1 pick. #2/#3 from the ranking still get saved as
backups.

**A pixel-width check only counts if those pixels were captured, not upscaled.** A frame
screenshotted from a portrait video in a landscape viewport can report 750px while
carrying ~440px of real detail; resizing or zooming after the fact never adds information
back. On the agent-controlled-browser path, capture rotated (Step 1) so the number and the
detail agree — and note that path has no video file to re-grab from, so its screenshots
*are* the thumbnail source and their capture resolution is the only resolution you get.
**Check the file you're about to upload** — `identify` (ImageMagick) or
`python3 -c "from PIL import Image; print(Image.open('<path>').size)"`. **Reject anything
under 512px wide** (the server rejects it too) and re-grab before picking again; don't
persist a low-res frame just because it's the best-composed one available.

Record your #1 pick's `thumb_*.jpg` path — that's the one to persist as the recipe's
thumbnail in Step 6.5 below. Pass #2 and #3's frame paths to `save_recipe`/`update_recipe`
as thumbnail candidates too (see Step 6.5) — nourishible keeps them as a 60-day reviewable
backup, it just doesn't show them anywhere yet. Those two are fine to send as reading
frames; only the #1 pick needs the full-resolution re-grab.

**Never fall back to a platform-provided thumbnail** (YouTube's
`i.ytimg.com/vi/<id>/maxresdefault.jpg`, an Instagram CDN URL, etc.) just because it's easier
to grab from video metadata. It isn't a frame *you* picked for quality — it's the creator's
click-through art, so it typically carries a face, a caption bar, or an arrow graphic — and
platform CDN links can be signed or expiring, leaving the recipe thumbnail-less later.

Concretely: **do not pass `thumbnailUrl` to `save_recipe` or `update_recipe`.** That field
exists for recipes typed in by hand with an image already on the web; it is not an escape
hatch for this flow, and passing a platform CDN URL there is how two extractions on 29 Aug
2026 shipped with `i.ytimg.com` art instead of a picked frame. The thumbnail always travels
as bytes — `thumbnailImageBase64` on `save_recipe`, or `imageBase64` on
`set_recipe_thumbnail`. If you have no usable frame at all, save with no thumbnail and say
so; that is the only acceptable alternative.

## Step 6 — write the output

Save the recipe JSON to a file in the working directory the script reported (or `--out
DIR` if the caller specified one). Then show the user: the recipe as a readable summary
(title, ingredients, steps with any matched timestamps, servings/time), the source credit
(creator handle + link — **always** include this, never presented as this skill's own
content), and the "Worth double-checking" list from Step 5.

## Step 6.5 — persist to nourishible

Don't stop at the JSON file — the point of this skill is a saved recipe the user can open
in the nourishible app, under *their own* account.

### Connect nourishible, if you haven't already

If you can see `save_recipe`, `update_recipe`, `create_thumbnail_upload`, `list_my_recipes`,
`get_my_recipe`, `search_recipes`, and `get_recipe` as callable tools in this session, skip
to "Save the recipe" below — you're already connected. **If you're running as the
`nourishible` Claude Code plugin**, this is already true by construction: the plugin bundles
`.mcp.json` alongside this skill, so the MCP server was registered the moment the plugin was
installed — the only thing that can still be missing is the OAuth sign-in itself (see below).

If those tools aren't available, tell the user this skill needs a connected nourishible
account to save anything, and walk them through connecting it — this is a one-time,
per-agent setup, not something to redo per recipe:

**Do it for them in one pass — don't hand them a checklist.** Fetch
`https://mcp.nourishible.com/` and follow it:
it covers registering the MCP server *and* (re)installing this skill in the same pass, with
the exact command or config file for the agent you're running as, and it's safe to run when
one half is already in place. If you can't fetch it, register the server directly — remote
HTTP MCP server named `nourishible` at **https://mcp.nourishible.com/mcp** (Claude
Code: `claude mcp add --transport http --scope user nourishible <that url>`; Claude Desktop
and other clients have their own "add remote server" flow, some GUI-only — for those, tell
the user the one thing to click rather than skipping it).

**Connecting the server is the login** — the first tool call triggers the agent's own
browser-based OAuth flow (a real nourishible sign-in page, then an "Allow" screen naming
this skill/agent), and the agent stores the resulting token itself. There's no separate CLI
login command, no local server to clone/build/run, and nothing to build — this is the only
connection path this skill uses. Every install path still requires this same OAuth step;
the one-step install only removes the separate "add the MCP server" errand, not the sign-in
itself — that part is inherently tied to *this* user's account and can't be skipped or done
on their behalf.

Don't try to improvise the OAuth flow yourself from raw HTTP calls — it already has one
correct implementation on nourishible's side; a hand-rolled copy here would just be a
second place for it to drift out of sync and break.

### Save the recipe

**A save is `save_recipe`/`update_recipe` *and* a thumbnail upload together — not done
until both have succeeded.** This is cheap: Step 5.5 already ranked the frames you read in
Step 2 and re-grabbed the #1 pick's timestamp at full resolution, so setting it is one more
tool call on a file already on disk — not a re-download and not a fresh extraction pass. Never report a recipe as saved, and never move to Step 7,
having called only `save_recipe`/`update_recipe` — a thumbnail-less "success" is a save you
still owe the other half of.

1. **Re-run the Step 0.5 dedup check** immediately before saving (see that section).
2. **New recipe:** inspect the live `save_recipe` description before calling it. Some
   hosted deployments require a video recipe's picked thumbnail in the **initial** save
   (the recipe has no id yet, so `create_thumbnail_upload` cannot be used first). When the
   tool reports that requirement, encode the #1 frame as `thumbnailImageBase64` and include
   it in this `save_recipe` call; use the 512×384 / quality-75 fallback preparation below,
   then verify the returned `thumbnailUrl`. Otherwise call `save_recipe` with the exact
   JSON from Step 3 (including the `timestampSeconds` values from Step 3.5) and use the
   direct-upload path in the next step. **Re-extract of an existing one** (Step 0.5 found a
   match and the user confirmed): call `update_recipe` with that recipe's `id` and only the
   fields that changed — omitted fields are left untouched, so don't resend the whole object
   out of habit.
3. **If `save_recipe`'s response has `duplicate: true` instead of a saved recipe:**
   nourishible found an existing recipe for this video server-side that Step 0.5 missed
   (a race with another save on this account is the normal cause) and created nothing.
   This is not a failure — don't retry the call, and don't treat it as an error to work
   around. Use the response's `existingRecipeId`/`existingTitle` the same way Step 0.5
   handles a match: tell the user it's already saved and ask whether they want to
   re-extract, then `update_recipe` on that id if they do (still finishing with the
   thumbnail step below if you do). Skip the rest of this list for this attempt otherwise.
4. **Thumbnail — required, immediately, same turn.** If the initial-save contract above
   already stored the thumbnail, verify its `thumbnailUrl` and continue. Otherwise upload
   it directly: call `create_thumbnail_upload` with the saved/updated recipe's `id`. It returns a
   short-lived, single-use `uploadUrl` and a ready-to-run `command`. PUT the raw bytes:

   ```bash
   curl -X PUT --data-binary @thumb_0000.jpg -H 'Content-Type: image/jpeg' "<uploadUrl>"
   ```

   Send Step 5.5's #1 pick — the full-resolution `thumb_*.jpg` re-grab, not the reading
   frame you ranked — **at full resolution. Do not downscale it and do not re-compress it.**
   The bytes never pass through your context on this path, so image quality costs you
   nothing; a 200KB 1280x720 frame is as cheap to send as a 7KB one. For #2/#3, request a
   link each with `kind: "candidate"` and PUT them the same way. Do this every time there's
   a frame to give — a recipe saved without a thumbnail shows blank in the library. The one exception is Step 5.5 genuinely finding zero usable frames (no food
   visible in any frame, not just "the best one is mediocre") — in that specific case only,
   say plainly in your Step 6 summary that the recipe saved with no thumbnail and why,
   rather than silently skipping the call or fabricating a substitute (see Step 5.5's note
   on platform-provided thumbnails).

   **Crop for composition, not for size.** Cropping still matters — it's what makes the
   card the dish rather than the dish plus half a countertop — but crop to a **fixed aspect
   ratio** (4:3, or 1:1), never a free-form "tight" box. Free-form tight crops are what
   produced the 900x339 and 900x382 letterbox strips that shipped in late Aug 2026, with the
   bowl sliced off top and bottom. If the dish doesn't fit a 4:3 window without cutting into
   it, widen the crop and accept some background — background beats an amputated bowl. Crop
   away a burnt-in caption where the composition allows, so the card is the food rather than
   the food plus someone else's subtitles.

   ```python
   from PIL import Image
   TARGET_ASPECT = 4 / 3
   im = Image.open(FRAME).convert('RGB')      # the thumb_*.jpg re-grab
   w, h = im.size
   nw, nh = (int(h * TARGET_ASPECT), h) if w / h > TARGET_ASPECT else (w, int(w / TARGET_ASPECT))
   left, top = (w - nw) // 2, (h - nh) // 2   # shift to centre the food, keep nw/nh
   im.crop((left, top, left + nw, top + nh)).save(OUT, 'JPEG', quality=92, subsampling=1)
   ```

   Note quality 92 and no `thumbnail()` call: on the upload path there is no reason to
   shrink or to compress hard. The only floor that still applies is the server's — **at
   least 512px wide**, or the upload is rejected with `thumbnail_too_small`.

   **Fallback, only if you genuinely cannot run shell commands:** `set_recipe_thumbnail`
   with `imageBase64` (or `thumbnailImageBase64` on `save_recipe`) still works. Be aware
   what it costs: base64 runs ~0.72 tokens per character, and you pay it twice — once
   reading the string in, once emitting it verbatim — so a 40KB JPEG is roughly 39k tokens
   each way. On that path only, downscale to 512x384 at quality 75 first, step down
   quality 75 -> 70 -> 65 -> 60 if a call fails, never below 512px wide, and **re-fetch the
   returned `thumbnailUrl` and look at the image** before calling it done: this path has
   silently stored truncated JPEGs while returning a normal-looking success (observed
   24 Aug 2026), and nothing in the response reveals it. The upload path has no such
   failure mode — the bytes are stored exactly as sent.

5. Read back each tool's response for the real `id`/`slug` (and, once thumbnailed, confirm
   the thumbnail is set) that nourishible assigned, and use that — not anything you
   invented — in your Step 6 summary to the user.
6. **If the response includes a `safety` field** (nourishible computes this server-side
   for recipes that read as baby/infant food — you don't need to do anything to trigger
   it), relay its `flags` plainly in your Step 6 summary: each flag's `message`, verbatim.
   This is deterministic, cited guidance the server computed, not your own judgment — don't
   add to it, soften it, or decide it doesn't apply. Never phrase the *absence* of a
   `safety` field as "this is safe for babies" — nourishible didn't check every possible
   hazard, only 14 specifically cited ones, and a recipe that doesn't read as baby food at
   all is never checked in the first place.

## Step 7 — clean up

If there's no likely follow-up on this specific video, `rm -rf` the working directory once
the JSON has been shown/saved wherever the user wants it kept. If the user might ask to
re-extract or adjust, leave it.

## Failure modes and handling

- **Setup preflight failed (YouTube)** → run `python3 "${SKILL_DIR}/scripts/setup.py"`
  (auto-installs ffmpeg/yt-dlp via brew on macOS, scaffolds the `.env`). Don't ask about
  the API key — same first-run defaults as Step 0 (proceed with `--no-whisper`).
- **No transcript available (YouTube)** → captions missing AND (no Whisper key OR Whisper
  API failed). Proceed frames-only and tell the user.
- **Download fails (YouTube)** → `download.py` retries alternate yt-dlp player clients and
  downloaders automatically; if every attempt fails (common signature: SSL/TLS to
  `googlevideo.com`), `watch.py` keeps captions/metadata and falls back to the official
  YouTube thumbnail as a single frame. Tell the user plainly, suggest
  `python3 scripts/setup.py` (installs `curl_cffi`), `WATCH_COOKIES_FROM_BROWSER=chrome`,
  and upgrading yt-dlp — do not hand-roll infinite retries beyond what the scripts already do.
  Login-required or region-locked videos are a different failure; say so explicitly.
- **Blocked by this environment's own network policy** (any platform) — some agents run in a
  sandbox whose outbound traffic goes through a proxy with its own fixed domain allowlist,
  separate from anything this skill or the user controls. The signature is a connection
  refused/blocked *before* `yt-dlp`/the download even starts trying — e.g. a proxy
  `403`/`host_not_allowed`-style error naming the host, not a normal HTTP error from the
  platform itself. When you see this:
  - **Don't retry it, and don't try to work around it** — not via `curl`, not via an
    alternate downloader or a different tool. The same proxy restriction applies to every
    outbound request this process makes, so a workaround just fails the same way one call
    later, having burned a turn to learn nothing new.
  - **Don't confuse this with a real download/login/region failure** (the bullet above) —
    a proxy block happens before the platform is ever reached, so nothing about the video
    itself (privacy, region, login) is the cause. Say so plainly, so the user doesn't waste
    time on the wrong fix (an account, a VPN, a different URL).
  - **This can't be fixed from inside the skill or the install flow** — it's the hosting
    environment's own egress policy (an account/environment setting on whatever platform is
    running this agent), not a nourishible or `recipe-nourishible` limitation. Say plainly
    that the specific domain would need to be added to that environment's allowlist, and
    that's a change only the user (or whoever administers that environment) can make.
  - **Offer the fallback that still works:** ask the user to send the note/video's content
    directly instead — a screenshot or export of the images and text, or the video file
    itself — and structure the recipe from that, same as any other input. This keeps the
    skill useful even when the fetch is blocked outright.
- **`capture-only.sh` fails (Instagram)** — this is a different failure surface than the
  YouTube path:
  - No window found ("Could not find a browser window playing Instagram") — the post
    isn't open/visible in a Chrome tab. Ask the user to open it and confirm it's playing,
    don't retry blindly.
  - `setup.py --check-capture` exits non-zero — run `--install-capture` and follow its
    output; if it stops at "Screen Recording permission not granted," that needs the user
    to act in System Settings, not another retry from you.
  - Empty `transcript.clean.txt` — not a failure. Audio capture needs a virtual output
    device the user may not have; proceed on `onscreen.clean.txt` and frames alone, which
    is usually enough (ingredients/quantities are more often on-screen than spoken).
  - `onscreen.clean.txt` mostly empty too, with real frames present — the crop likely
    missed the reel (wrong window/display). Tell the user plainly rather than guessing at
    a recipe from frames with no readable text.
- **Instagram, but you can't run the capture scripts** (remote agent, non-Darwin shell,
  no Screen Recording permission for your shell, scripts not on the machine with Chrome) —
  this is **not** a dead end. Use a signed-out browser you control if you have one, else
  the agent-controlled browser route (`references/instagram.md`). Only report Instagram as
  unavailable when those are missing too, and say which piece is missing rather than
  "Instagram is macOS-only".
- **Browser path fails (Instagram)** — see the route's own failure modes in
  `references/instagram.md`. The ones that matter most: never navigate a **signed-in**
  browser to the post to "fix" a missing tab, never reload to retry a login wall, and in
  the signed-out browser never navigate the tab away before the thumbnail file is saved.
- **Thumbnail upload failed** — if `create_thumbnail_upload` isn't available or the PUT
  can't run, fall back to `set_recipe_thumbnail` with base64 at 512×384/quality 75 and
  verify the stored image (Step 6.5, item 4). A `thumbnail_too_small` rejection means the
  frame is under 512px wide: re-grab it with `--thumbnail-at`, don't upscale it. An expired
  or already-used link is not an error to retry — request a new one. Never skip the
  thumbnail, substitute a platform CDN URL, or pass `thumbnailUrl`.
- **No usable ingredient list found anywhere** (frames, caption, audio) — don't fabricate
  one. Tell the user the video doesn't appear to state ingredients/quantities clearly
  enough to extract, and offer to proceed with what's inferable (dish name + technique
  only) if they still want a draft.
- **Video isn't actually a recipe** — say so plainly rather than forcing a recipe-shaped
  output onto unrelated content.
- **Multiple recipes in one video** (e.g. "3 ways to use leftover rice") — ask the user (via
  `AskUserQuestion`) which one they want, or whether they want all of them as separate
  recipe JSONs, rather than merging them into one incoherent recipe.
- **Not connected to nourishible** — a save-tool call fails with a clear error rather than
  a silent failure; stop and walk the user through connecting (see Step 6.5), don't retry
  blindly.

## Token efficiency

Frames dominate everything else. They're capped by *area* (0.8 MP), not width, so a
portrait reel and a landscape video cost the same ~800-1070 image tokens per frame; before
that cap a 9:16 reel cost 3.2x what a 16:9 video did at the same `--resolution`. A 60-80
frame pass is therefore ~50-85k image tokens. The transcript is cheap by comparison — a few
thousand tokens at most for a 10-minute video.

The four levers that matter, in order of size:

1. **Only read the reference file your platform needs** (see "Reference files" above). A
   YouTube run that reads `references/instagram.md` anyway has paid ~5k tokens for
   procedure it will never execute.
2. **Set the frame budget from the caption/description** (Step 1) before extracting.
   Dropping to `--detail efficient` when the text already carries a complete quantified
   ingredient list roughly halves the frame spend and discovers nothing less.
3. **`--section` screening** (Step 1) before downloading anything long: the difference
   between decoding 90 seconds and 20 minutes.
4. **Grab the Step 5.5 shortlist with `--timestamps`, not a `--thumbnail-at` loop** —
   ~4.2k tokens for 12 candidates instead of ~33k, and it actually keeps all 12 files.

The final thumbnail is free on the `create_thumbnail_upload` path and expensive on the
base64 fallback (~39k tokens each way for a 40KB JPEG, paid on read and again on emit),
which is the whole reason to prefer the upload.

What *not* to trim: frame dedup is deliberately conservative on localised change, because
a recipe reel that states its ingredients as a small text overlay over an unchanging pan
produces frames that are near-identical on average and completely different in the only
part that matters. Don't tighten it to save frames.

## Security & Permissions

Summary: this skill runs `yt-dlp`/`ffmpeg` locally, writes frames and audio to a working
directory under the system temp dir, sends only an extracted audio clip to Groq/OpenAI
Whisper when native captions are missing, and calls the connected nourishible tools to
save the recipe. It does not upload the video, does not log in to any platform, and does
not persist anything outside the working directory and the user's own nourishible account.

The Instagram local-capture path additionally asks for macOS Screen Recording, Automation
access to Chrome, and possibly Microphone — the YouTube path never touches these.

**Full audit detail — every binary, every network destination, every permission, and the
"what this skill does NOT do" list — is in `${SKILL_DIR}/references/security.md`.** Read it
before first use, or whenever a user asks what the skill does to their machine.

## Attribution

This skill is the merged, publishable successor to work from nourishible's private
repository, building on **`/watch`** (MIT, by
[bradautomates](https://github.com/bradautomates/claude-video)) for the download/frame/
transcription approach, nourishible's internal `/recipe-extract` for the structuring, and
`ig-saved` for the Instagram capture pipeline. Full credit, licence notes, and what was
and wasn't carried forward: `${SKILL_DIR}/references/attribution.md`.
