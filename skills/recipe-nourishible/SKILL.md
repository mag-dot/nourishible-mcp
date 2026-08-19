---
name: recipe-nourishible
version: "1.0.0"
description: Turn a recipe video (Instagram Reel, YouTube Short/video) into a structured recipe — title, tagged ingredients, numbered steps matched to the video moment they happen at, servings, source credit, a picked thumbnail — and save it straight to your nourishible account. Downloads the video, reads on-screen text, and cross-references the transcript and caption itself; no separate OCR/extraction API. Connects to nourishible via a hosted MCP server — no local server to build, no CLI login step.
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

## Resolve `SKILL_DIR` (do this before any command)

Set `SKILL_DIR` to the absolute path of the directory containing **this** SKILL.md you
just Read — your harness told you that path in the Read result. The bundled script is
always a direct sibling of this file, in every install layout (a Claude Code plugin, a
manual clone, `~/.claude/skills/`, `~/.codex/skills/`, …):

```bash
SKILL_DIR="<absolute path of the directory containing the SKILL.md you Read>"
WATCH_SCRIPT="$SKILL_DIR/scripts/watch.py"
if [ ! -f "$WATCH_SCRIPT" ]; then
  echo "ERROR: could not find $WATCH_SCRIPT — is scripts/ present as a sibling of this SKILL.md?" >&2
  exit 1
fi
```

Substitute that literal path for `${SKILL_DIR}` in every command below. This works on
every harness that can run bash and read local image files (Claude Code, Claude Desktop
with a local MCP client, Cursor agent mode, Codex CLI, Gemini CLI, …) without relying on
any harness-specific environment variable.

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
  3. Encourage a Whisper API key and ask the preference question below, then write the
     selected values into `~/.config/watch/.env` and set `SETUP_COMPLETE=true`.
- **`can_proceed: false` and `first_run: false`** → setup was finished before but the
  environment regressed (e.g. `missing_binaries` after an OS change). Run the installer to
  remediate, then proceed. Don't re-ask preferences.

A missing Whisper key is *encouraged to fix, not required*: on a genuine first run `status`
will read `needs_key` even when binaries are present — that's your cue to encourage a key,
not a blocker.

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
| `3` | Genuine first run with no Whisper API key | Run installer to scaffold `.env`, then encourage a key (the user may decline — proceed with `--no-whisper`) |
| `4` | Both missing | Run installer, then encourage a key |

The installer is idempotent — safe to re-run:

```bash
python3 "${SKILL_DIR}/scripts/setup.py"
```

On macOS with Homebrew, it auto-installs `ffmpeg` and `yt-dlp`. On Linux/Windows, it prints
the exact install commands for the user to run. It scaffolds `~/.config/watch/.env` with
commented placeholders and default settings at `0600` perms.

**If an API key is still missing after install:** use `AskUserQuestion` to ask the user
whether they have a Groq API key (preferred — cheaper, faster) or an OpenAI key. Then write
it into `~/.config/watch/.env` — set `GROQ_API_KEY=...` or `OPENAI_API_KEY=...`. If they
don't want to set up Whisper, proceed with `--no-whisper`; videos without native captions
will come back frames-only.

**First-run detail preference:** after the installer has scaffolded `~/.config/watch/.env`,
use `AskUserQuestion` to ask one question — default detail (one dial), presented in this
exact order, lightest to heaviest, with `(recommended)` on `balanced` even though it isn't
first:

- `transcript` — no frames at all, transcript only (skips video download when captions exist).
- `efficient` — fast keyframe pass (cap 50).
- `balanced` (recommended) — scene-aware frames (cap 100, default).
- `token-burner` — scene-aware, uncapped (maximum fidelity; high token cost).

Write the answer directly into `~/.config/watch/.env` on its own line, **no trailing inline
comment**:

```bash
WATCH_DETAIL=balanced
```

Once dependencies, the API-key choice, and this preference are handled, write or update
`SETUP_COMPLETE=true` in the same file. Don't ask this again once it's set.

## When to use

- User pastes an Instagram Reel or YouTube Short/video link and asks to save/extract it as
  a recipe, or types `/recipe-nourishible <url>`.
- User asks "what's the recipe in this video" for something that is clearly a
  cooking/recipe video.

Not for: general video Q&A unrelated to recipes, blog/website recipe scraping (out of
scope — no download step applies), TikTok (not currently supported by the bundled
download script).

**Instagram is macOS-only.** YouTube works everywhere this skill runs. Instagram goes
through local screen capture (Step 1), which needs macOS's Screen Recording permission —
there's no equivalent on Linux/Windows. Tell the user plainly if their platform isn't
Darwin and they paste an Instagram link; don't attempt it anyway.

## Step 0.5 — dedup check (do this before spending any download/frame budget)

Before calling the bundled script, check whether this exact video has already been saved
by this user. **Normalize both the incoming URL and every already-saved `sourceUrl` before
comparing** — a raw string/exact match misses real duplicates: YouTube URLs routinely carry
a tracking `&pp=...`/`&si=...`/`&t=...` param that has nothing to do with video identity.
Extract just the video id (the `v=` param, or the path segment after `youtu.be/` /
`shorts/`) from both sides and compare on that.

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
  legible, not just recognizable. This roughly quadruples image tokens per frame; accept
  that cost, it's the point of this skill.
- `--detail balanced` is the right starting point for most recipe Shorts (under ~90s,
  which covers the large majority of recipe content). For a longer-format video, consider
  `--detail token-burner` or focusing with `--start`/`--end` around the actual cooking
  steps if there's a long cold-open/intro to skip.
- If the video is bot-gated ("Sign in to confirm you're not a bot"), set
  `WATCH_COOKIES_FROM_BROWSER` (or pass `--cookies-from-browser BROWSER`) — this genuinely
  is a cookie-auth problem, unlike Instagram's.
- Pass `--out DIR` through as `--out-dir` if the user (or your caller) specified one;
  otherwise let it use the default tmp dir.

**Transcript-cue pass (do this for every recipe, not just when sparse):** after the first
run, scan the transcript for the moments a cook narrates quantities/technique ("add two
tablespoons of...", "let that go for five minutes", "fold in the..."), and for moments a
cook typically *acts* even without narrating it clearly (a cut to a sizzling pan, a bowl
being combined). Re-run once with `--timestamps` pinned to those moments (see "Transcript-
cue frames" below), pointed at the already-downloaded local file so it doesn't re-download.
This pass is what Step 3.5 (matching steps to video moments) depends on — a quantity or
action is often only correct/visible at one specific frame, not "somewhere in this scene."

**Other useful `watch.py` flags:**

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

### Instagram — local screen capture

Requires macOS (Screen Recording is a macOS-only mechanism). This is a **separate,
opt-in** profile from the YouTube setup above — a user who only ever pastes YouTube links
is never asked to install any of this. Verify it's ready before capturing:

```bash
python3 "${SKILL_DIR}/scripts/setup.py" --check-capture
```

Exit 0 means ready — go straight to the capture command below. A non-zero exit prints one
actionable line (what's missing, and the exact install command). Run that:

```bash
python3 "${SKILL_DIR}/scripts/setup.py" --install-capture
```

This installs `whisper-cli`/`node`/`swiftc` via brew if missing, downloads the Whisper
model, compiles the OCR binary, and — if Screen Recording permission isn't granted — opens
System Settings to the right pane and exits non-zero, telling the user to grant it and
re-run. **Don't loop silently on that** — surface it to the user; granting a macOS
permission needs them, not you.

Once ready, tell the user to open the Instagram post **in Google Chrome** (this is
Chrome-specific — it drives Chrome via AppleScript, other browsers aren't detected) and
have it visible and playing, then run:

```bash
"${SKILL_DIR}/scripts/capture/capture-only.sh" 45
```

This finds the browser window playing the reel via the accessibility API (no manual
window-picking), shows a one-frame preview for you to confirm, records the screen for the
given number of seconds, and prints `CAPTURE_DIR=<path>` on success — parse that line for
the directory containing what you need:

- `frame_*.jpg` — sampled video frames, same as the YouTube path gives you.
- `caption.txt` — **the post caption as exact text**, read from the page's
  `og:description` rather than OCR'd off pixels. Prefer this over the caption text that
  also appears in `onscreen.clean.txt`: OCR truncates at the fold (a real capture cut off
  at exactly "This little bowl was made with:", losing every ingredient below it) and
  introduces transcription errors. May be absent — if Chrome's "Allow JavaScript from
  Apple Events" is off, or the tab closed mid-capture — in which case fall back to the OCR
  text.
- `onscreen.clean.txt` — deduped OCR of on-screen text (ingredient overlays, step
  callouts). Also picks up caption text, since the crop includes the caption panel beside
  the video — treat `caption.txt` as authoritative where the two disagree.
- `transcript.clean.txt` — Whisper transcript, or empty if no audio was captured (system
  audio needs a virtual device the user may not have installed; on-screen text carries
  most of a recipe's actual content regardless, so proceed with what's there rather than
  treating a silent transcript as a failure).

Read these the same way you'd read the YouTube path's output in Step 2 — `frame_*.jpg`
maps to the frame paths `watch.py` would have printed, `onscreen.clean.txt` and
`transcript.clean.txt` are the OCR/transcript evidence streams.

**Why this is the compliant path, not a workaround:** nothing here makes an automated
request to Instagram. The user opens and plays the post themselves; the script only
records what's already rendered on their own screen, the same way a screen-recording app
would. See [`docs/capture/CONTRACT.md`](../../docs/capture/CONTRACT.md) — the binding rule
this whole design exists to satisfy is *"content enters only because a human caused it to
play."* Don't build around this by scripting the play button, opening the URL yourself, or
walking a list of posts unattended — those cross from "recording your own screen" into
"automated access," which is exactly what's prohibited.

**If `capture-only.sh` reports it couldn't find the reel window**, the post likely isn't
open and playing in a visible Chrome tab — ask the user to check, don't retry blindly.

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
  "sourceUrl": "string (the URL you were given)",
  "sourcePlatform": "instagram | youtube",
  "creatorHandle": "string",
  "thumbnailFramePath": "path to the single best-representative frame from Step 1 (not a new download — pick from what you already extracted)",
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

The saved schema only carries a single thumbnail, but still do this ranking — it's what
feeds that one field today and what a future multi-image gallery would consume without
redoing the work. From the frames you already read in Step 2, pick the 3 strongest
candidates using these criteria, in order:

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
part-black), or where text/graphics cover a substantial part of the dish itself (a short
caption along the bottom edge is fine, a title card plastered across the food is not).

**Check your #1 pick's actual pixel width before moving on** — `identify` (ImageMagick) or
`python3 -c "from PIL import Image; print(Image.open('<path>').size)"` on the frame file.
Composition can look right in a downscaled preview and still be a soft, blurry image once
it's the full-size card/OG thumbnail everyone sees — Step 1's `--resolution 1024` should
already guarantee this, but nothing enforces that flag was actually honored (a re-run
without it, a caller-supplied `--out-dir` pointed at frames from an older invocation, etc.).
**Reject anything under 512px wide** and re-extract at `--resolution 1024` before picking
again — don't persist a low-res frame just because it's the best-composed one available; a
sharper second-best composition beats a soft #1.

Record your #1 pick's frame path — that's the one to persist as the recipe's thumbnail in
Step 6.5 below. Note the #2 and #3 picks in your summary to the user even though there's
nowhere in the schema to persist them yet.

**Don't skip this and fall back to a platform-provided thumbnail** (YouTube's
`i.ytimg.com/vi/<id>/hqdefault.jpg`, an Instagram CDN URL, etc.) just because it's easier to
grab from video metadata — it isn't a frame *you* picked for quality (no control over
hands/face/text in it), and platform CDN links can be signed/expiring. Always upload an
actual picked frame via `set_recipe_thumbnail`.

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

If you can see `save_recipe`, `update_recipe`, `set_recipe_thumbnail`, `list_my_recipes`,
`get_my_recipe`, `search_recipes`, and `get_recipe` as callable tools in this session, skip
to "Save the recipe" below — you're already connected.

If those tools aren't available, tell the user this skill needs a connected nourishible
account to save anything, and walk them through connecting it — this is a one-time,
per-agent setup, not something to redo per recipe:

- **The normal path — a remote MCP server, no local install:** point them at the exact URL
  and instructions on **nourishible.com/mcp**, and if their agent supports adding a remote
  MCP server directly (Claude Code: `claude mcp add --transport http nourishible <url from
  that page>`; Claude Desktop and other MCP clients have their own equivalent "add remote
  server" flow), that's the whole setup. **Connecting the server is the login** — the first
  tool call triggers the agent's own browser-based OAuth flow (a real nourishible sign-in
  page, then an "Allow" screen naming this skill/agent), and the agent stores the resulting
  token itself. There's no separate CLI login command for this path, and nothing to build.
- **Fallback — a local MCP client:** for an agent that can't add a remote MCP server, point
  them at the `mcp/` package in this same repository (`mcp/README.md`) — a local server they
  clone/build/run themselves, with its own one-time `npm run login` step. Only needed when
  the remote path above genuinely isn't supported.

Don't try to improvise the OAuth flow yourself from raw HTTP calls — it already has one
correct implementation on nourishible's side; a hand-rolled copy here would just be a
second place for it to drift out of sync and break.

### Save the recipe

1. **Re-run the Step 0.5 dedup check** immediately before saving (see that section).
2. **New recipe:** call `save_recipe` with the exact JSON from Step 3 (including the
   `timestampSeconds` values from Step 3.5). **Re-extract of an existing one** (Step 0.5
   found a match and the user confirmed): call `update_recipe` with that recipe's `id` and
   only the fields that changed — omitted fields are left untouched, so don't resend the
   whole object out of habit.
3. **If `save_recipe`'s response has `duplicate: true` instead of a saved recipe:**
   nourishible found an existing recipe for this video server-side that Step 0.5 missed
   (a race with another save on this account is the normal cause) and created nothing.
   This is not a failure — don't retry the call, and don't treat it as an error to work
   around. Use the response's `existingRecipeId`/`existingTitle` the same way Step 0.5
   handles a match: tell the user it's already saved and ask whether they want to
   re-extract, then `update_recipe` on that id if they do. Skip the rest of this list for
   this attempt.
4. **Thumbnail:** call `set_recipe_thumbnail` with the saved/updated recipe's `id`. What you
   pass depends on which connector you're using — check which tool description you actually
   see, since the two connectors take this differently:
   - **Remote MCP server:** pass the picked frame's image bytes, base64-encoded, as
     `imageBase64` — a remote server can't read a file path off your machine. Read the
     frame file and encode it yourself before calling the tool.
   - **Local `mcp/` client:** pass the local filesystem path to the JPEG directly as
     `filePath` — this connector runs on the same machine as you, so it reads the file
     itself.
   Do this every time there's a frame to give it — a recipe saved without this call shows
   with no thumbnail in the library.
5. Read back the tool's response for the real `id`/`slug` nourishible assigned, and use
   that (not anything you invented) in your Step 6 summary to the user.
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
  (auto-installs ffmpeg/yt-dlp via brew on macOS, scaffolds the `.env`). For API key, ask
  via `AskUserQuestion` and write it to `~/.config/watch/.env`.
- **No transcript available (YouTube)** → captions missing AND (no Whisper key OR Whisper
  API failed). Proceed frames-only and tell the user.
- **Download fails (YouTube)** → yt-dlp's error goes to stderr. If it's a login-required or
  region-locked video, tell the user plainly; do not keep retrying.
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

This skill burns tokens primarily on frames. Order of magnitude: 80 frames at 512px wide is
roughly 50-80k image tokens; bumping to 1024px (this skill's default, for legible on-screen
text) roughly quadruples that. The transcript is cheap by comparison — a few thousand
tokens at most for a 10-minute video.

## Security & Permissions

**What this skill does:**
- Runs `yt-dlp` locally to download the video and pull native captions when the source
  supports them (public data; the request goes directly to whatever host the URL points
  at).
- Runs `ffmpeg`/`ffprobe` locally to extract frames as JPEGs and, when Whisper is needed, a
  mono 16 kHz audio clip.
- Sends the extracted audio clip to Groq's Whisper API (`api.groq.com`) when `GROQ_API_KEY`
  is set (preferred — cheaper, faster), or OpenAI's (`api.openai.com`) when
  `OPENAI_API_KEY` is set and Groq is not.
- Writes the downloaded video, frames, audio, and an intermediate transcript to a working
  directory under the system temp dir (or `--out-dir`) so you can `Read` them.
- Reads/creates `~/.config/watch/.env` (mode `0600`) to store the Whisper API key(s) and a
  `SETUP_COMPLETE` marker.
- Calls the `save_recipe`/`update_recipe`/`set_recipe_thumbnail`/`list_my_recipes`/
  `get_my_recipe`/`search_recipes`/`get_recipe` nourishible tools (Step 6.5) once
  connected — these persist the structured recipe (and a thumbnail, if picked) to the
  user's real nourishible library. That's the point of Step 6.5, not a side effect to be
  surprised by.

**On Instagram specifically** (`scripts/capture/`), this skill asks for real system
permissions the YouTube path never touches — worth being explicit about rather than
letting it surprise the user mid-run:
- **Screen Recording** (macOS) — required for `capture-only.sh` to record anything at all.
  `setup.py --install-capture` opens System Settings to the right pane when this isn't
  granted; it cannot grant it for the user, by OS design.
- **Microphone**, only if no virtual audio device (BlackHole/Loopback) is installed —
  `capture.sh` falls back to it rather than failing, and says so plainly in its output.
- **Automation access to Google Chrome** (AppleScript) — to find the reel window and read
  the caption text. Nothing else is scripted in Chrome; no navigation, no clicking, no
  form-filling.
- Nothing captured is sent anywhere except the frames/transcript/OCR text that already
  feed into Step 2/3's structuring, same as the YouTube path. The OCR pass
  (`scripts/capture/ocr.swift`) runs entirely on-device via Apple's Vision framework — no
  network call, no API key.
- **No automated request is ever made to Instagram.** The recording captures what's
  already rendered on the user's own screen because the user opened and played the post —
  see [`docs/capture/CONTRACT.md`](../../docs/capture/CONTRACT.md) for why that distinction
  is load-bearing, not incidental, and is binding on this skill, not just a suggestion.

**What this skill does NOT do:**
- Does not upload the video itself to any API — only the extracted audio goes out, and
  only when native captions are missing and Whisper isn't disabled.
- Does not access any platform account beyond public data (no login, no session cookies,
  no posting). Does not attempt an Instagram cookie/API fallback if capture fails — that
  path is confirmed broken upstream, not a corner case to retry into.
- Does not call any third-party API for extraction itself — Instagram's OCR pass is
  on-device Vision, not a hosted service; the structuring itself happens in your own
  reasoning, same as any other skill output.
- Does not implement its own OAuth/network client for the save step — it only ever calls
  already-connected tools; if none are connected, it stops and tells the user to connect
  one rather than inventing a parallel auth path.
- Does not persist anything outside the working directory *and* the user's own nourishible
  account via the connected tools.

**Bundled files:**
- `scripts/watch.py` (entry point), `scripts/download.py` (yt-dlp wrapper),
  `scripts/frames.py` (ffmpeg frame extraction), `scripts/transcribe.py` (caption
  selection + Whisper orchestration), `scripts/whisper.py` (Groq/OpenAI clients),
  `scripts/config.py` (shared config helpers) — the YouTube path.
- `scripts/setup.py` — preflight/installer for both paths (`--check`/`--install` for
  YouTube, `--check-capture`/`--install-capture` for Instagram, gated separately so a
  YouTube-only user is never asked to install the Instagram half).
- `scripts/capture/` (`capture.sh`, `capture-only.sh`, `read-caption.sh`, `ocr.swift`,
  `dedupe-loop.mjs`) — the Instagram path. See Attribution below for where this came from,
  and [`docs/capture/CONTRACT.md`](../../docs/capture/CONTRACT.md) before changing anything
  about how it acquires content.

Review all of the above before first use to verify behavior.

## Attribution

This skill is the merged, publishable successor to work that lived in nourishible's own
private repository:

- The YouTube download/frame-extraction/transcription approach (`scripts/*.py`, excluding
  `capture/`) originates from **`/watch`**, MIT-licensed, by
  [bradautomates](https://github.com/bradautomates/claude-video). That skill's own
  license/attribution is carried forward here — see its homepage for the original.
- The recipe-specific structuring, confidence-scoring, and thumbnail-selection approach
  originates from nourishible's own internal `/recipe-extract` skill, the reference
  implementation nourishible's backend extraction pipeline is descended from.
- The Instagram screen-capture pipeline (`scripts/capture/`) originates from `ig-saved`, an
  earlier project by the same team, retired into nourishible's private repository and
  vendored here in turn — window-detection/crop-geometry logic and the OCR/caption-reading
  approach are carried forward as-is; the parts specific to `ig-saved`'s own standalone
  local-tool use case (a prototype UI, a catalog store, a job queue) were not, since this
  skill's own structuring (Step 2/3) and nourishible's library already cover that ground.
  [`docs/capture/CONTRACT.md`](../../docs/capture/CONTRACT.md) is the acquisition rule this
  pipeline exists to satisfy — read it before changing anything about how content is
  captured.

If you're looking for the general-purpose (non-recipe) video-Q&A skill `/watch` itself
provides, its original, actively maintained version is at
[bradautomates/claude-video](https://github.com/bradautomates/claude-video) — this skill
is recipe-specific and doesn't attempt to replace that broader use case.
