# Instagram — reference

Read this when, and only when, the URL is an instagram.com link. Step 1 of SKILL.md
routes here. Nothing in this file applies to YouTube or Xiaohongshu.

Instagram has no fetch path: `yt-dlp`'s extractor returns HTTP 400 even with a valid
logged-in session (verified 15 Aug 2026, stable/nightly/TLS-impersonated). Don't try
cookie auth and don't retry it — content comes off a screen, by one of the two routes
below. Choose by what's actually reachable, not by the OS your shell reports:

1. Can you run `scripts/capture/capture-only.sh` on a Darwin machine? Use local capture.
2. Otherwise, do you have browser tools pointed at a Chrome the user can see? Use the
   agent-controlled browser path.
3. Only if neither is true, say plainly that Instagram can't be extracted from where
   you're running. An agent on Linux can still drive a macOS Chrome through a browser
   extension — check for browser tools before concluding "Instagram is macOS-only".

## Local screen capture (macOS)

**This is one of two Instagram paths.** It requires macOS (Screen Recording is a
macOS-only mechanism) *on the machine running these scripts*. If that isn't where you are
— a remote agent, a Linux/Windows user, a container — skip to
`### Instagram — agent-controlled browser` below rather than concluding Instagram is
unsupported. This is a **separate, opt-in** profile from the YouTube setup above — a user who only ever pastes YouTube links
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
would. See [`docs/capture/CONTRACT.md`](../../../docs/capture/CONTRACT.md) — the binding rule
this whole design exists to satisfy is *"content enters only because a human caused it to
play."* Don't build around this by scripting the play button, opening the URL yourself, or
walking a list of posts unattended — those cross from "recording your own screen" into
"automated access," which is exactly what's prohibited.

**If `capture-only.sh` reports it couldn't find the reel window**, the post likely isn't
open and playing in a visible Chrome tab — ask the user to check, don't retry blindly.

## Agent-controlled browser (any platform)

Use this when you can't run the macOS capture scripts — you're a remote/cloud agent, the
user is on Linux or Windows, or the skill's shell simply isn't the machine Chrome lives
on. It needs browser-automation tools wired to a Chrome the **user** is looking at
(Claude in Chrome's `mcp__claude-in-chrome__*`, or any MCP browser server offering
screenshots, page reads, and script evaluation). It needs no Screen Recording permission,
no `swiftc`, no Whisper, and no local `ffmpeg` — everything comes through the browser.

**The acquisition rule is identical, and it is not negotiable.** Read
[`docs/capture/CONTRACT.md`](../../../docs/capture/CONTRACT.md) before touching this path. In
short:

- **The user navigates to the post and presses play. You never do.** Do not call a
  `navigate` tool with an instagram.com URL. Do not click the play button. Do not open a
  post from a list, a saved collection, or a profile grid. Ask, then wait.
- Once the human has played it, reading that rendered page and screenshotting it is the
  same permitted act as recording their screen — you are the recorder, not the requester.
- **Never batch.** One post, because the user asked for that post. Walking several posts
  in a session is the pattern enforcement is built to catch, no matter how the frames are
  captured.

If the user's own browser is not already open on the post, ask them to open it. That ask
*is* the mechanism, not friction to design away.

#### Procedure

1. **Pick the browser.** List the connected browsers and have the user choose one (Claude
   in Chrome requires this before any browser action). Note the platform it reports — a
   macOS Chrome here means the local-capture path may also be available if your scripts
   can reach that machine; usually they can't, which is why you're here.
2. **Locate the post's tab.** Get the tab context and look for an `instagram.com/reels/…`
   or `/p/…` URL. If it isn't there, ask the user to open the post and play it, then check
   again. Never navigate there yourself.
3. **Read the caption.** Pull it from the page's own text or `og:description` — this is
   the exact equivalent of the local path's `caption.txt`, and the same precedence applies
   (see Step 2): it is often more complete than anything on screen, and it is real text
   rather than OCR, so prefer it over pixels wherever the two disagree.
4. **Rotate the video before capturing — this is the single biggest quality lever.**
   Reels are portrait (typically 1080×1920) and browser viewports are landscape. A
   portrait video fitted into a landscape viewport occupies a *narrow vertical strip*: on
   a 1298×724 viewport it renders about **440px wide**, no matter how you zoom. Your
   screenshot tool will happily hand back a larger image than that, but those extra pixels
   are **upscaled, not captured** — you get a soft, mushy frame and, worse, a pixel width
   that passes Step 5.5's ≥512px check while carrying less than half that in real detail.

   Fix it by rotating the video 90° so its long axis lands on the viewport's wide axis,
   then rotating the image back after capture. On the same viewport this lifts real
   capture from ~440px to ~1440px along the long edge — roughly **3× the linear detail**.
   Composite onto your own canvas so the platform's UI chrome isn't overlaid on the frame:

   ```javascript
   const v = document.querySelectorAll('video')[0]; v.pause();
   v.style.cssText = 'position:fixed;top:0;left:0;width:2px;height:2px;opacity:0.01;';
   const c = document.createElement('canvas');
   document.documentElement.appendChild(c);        // NOT body — body gets hidden below
   const H = innerHeight, W = Math.round(H * 16 / 9);   // 16:9 once rotated
   c.style.cssText = `position:fixed;top:0;left:0;width:${W}px;height:${H}px;z-index:2147483647;background:#000;`;
   c.width = W * 2; c.height = H * 2;
   document.body.style.visibility = 'hidden';      // hide the site's own UI
   window.__draw = async (t) => {
     await new Promise(r => { v.onseeked = r; v.currentTime = t; });
     const x = c.getContext('2d');
     x.setTransform(1,0,0,1,0,0); x.clearRect(0,0,c.width,c.height);
     x.translate(c.width/2, c.height/2); x.rotate(Math.PI/2);
     x.drawImage(v, -c.height/2, -c.width/2, c.height, c.width);
     x.setTransform(1,0,0,1,0,0);
   };
   ```

   Then `Image.transpose(Image.ROTATE_90)` in PIL undoes the clockwise canvas rotation.
   **Restore the page afterwards** (remove the canvas, clear the inline styles, unhide the
   body) — you altered a tab the user is sitting in.

   Note the coordinate space: screenshot pixels and CSS pixels differ, and not by
   `devicePixelRatio` — tools commonly cap or rescale. Measure the ratio once (screenshot
   width ÷ `innerWidth`) and scale your capture region by it.

5. **Capture frames by seeking.** Call your draw helper, wait ~1s for the paint, then
   capture a **zoomed screenshot of the canvas region only**. Batch these (seek → wait →
   capture, several per call) if your browser tool supports batching; one round trip per
   frame is painfully slow otherwise.

   **Sanity-check the real resolution before trusting it.** Ask what the video actually
   occupied on screen, not what your screenshot tool reported — if those disagree, you are
   looking at an upscale. `videoWidth`/`videoHeight` tell you the native size; the rendered
   box tells you what was truly sampled.

   **Seeking is only permitted inside content the human already played.** Ask the user to
   let the reel run through once before you start; then every seek reads a buffer their
   playback caused to load, and you have initiated nothing. Do not seek through a video
   nobody has watched — that turns buffering into a fetch you caused.

6. **Sweep, then fill gaps.** Start coarse (every ~3s for a 40s reel), read what you have,
   then re-capture at specific timestamps where a caption clearly changed between two
   frames or an ingredient went in unlabelled. This is the same idea as the YouTube path's
   transcript-cue pass, driven by on-screen text instead of a transcript.
7. **Save the thumbnail frame to disk.** Most browser screenshot tools accept a
   "save to disk" flag and return a path — take it for your Step 5.5 pick, so you have
   real bytes to upload later. This path has no video file to re-grab from, so the
   screenshot you save here *is* the thumbnail source and its capture resolution is the
   only resolution you get. Check the saved file's actual pixel width before using it
   (Step 5.5's ≥512px rule applies here exactly as it does everywhere else).

#### What you get, and what you don't

| Local capture gives you | This path gives you |
|---|---|
| `frame_*.jpg` | zoomed screenshots of the video region — equivalent, read them the same way |
| `caption.txt` | the page's own caption text — equivalent, and just as authoritative |
| `onscreen.clean.txt` (Vision OCR) | **you** read the overlay text straight off the frames; no OCR pass exists or is needed |
| `transcript.clean.txt` (Whisper) | **nothing** — there is no audio on this path |

The missing transcript is usually survivable for exactly the reason the local path already
notes: ingredients and quantities live on screen far more often than in narration. Say so
in your Step 5 notes rather than presenting the extraction as though audio was considered.

#### Failure modes

- **No browser tools in the session** — this path is unavailable. Don't improvise one with
  `curl`/`yt-dlp`; Instagram's fetch path is confirmed broken *and* prohibited. Tell the
  user, and offer running the skill locally on a Mac instead.
- **No connected browser, or the extension is offline** — ask the user to open Chrome with
  the extension connected. Don't retry blindly.
- **The tab isn't on the post** — ask; never navigate there yourself.
- **A login wall or age gate** — the user isn't signed in *in that browser profile*. Say
  so; do not attempt to sign in, and do not enter credentials under any circumstances.
- **Frames are black or the video won't seek** — the reel probably hasn't been played
  through. Ask the user to play it fully once, then retry.
- **Overlay text is illegible** — you're capturing at too low a resolution. Enlarge the
  video element and zoom to the video region rather than screenshotting the whole window.

## Carousels (multi-image `/p/` posts)

**Decide which of the two Instagram paths you're on before running anything.** A `/p/` URL
is not automatically a carousel — Instagram serves single images, videos and carousels all
under `/p/`. The distinguishing question is whether the post has a video: if it does, it's
the reel path above. A carousel of still images has no video, no audio and no duration, so
`capture-only.sh` is the wrong tool — it would record 45 seconds of a motionless slide and
hand Whisper silence to transcribe.

An `?img_index=N` parameter in the URL is a strong hint it's a carousel (it's how the web
app addresses slide N), but its absence proves nothing — it only appears once the user has
navigated between slides. When unsure, ask the user, or look at the preview frame.

Same preflight as the reel path (`--check-capture` / `--install-capture`, macOS-only, for
the same reason). Tell the user to open the post **in Google Chrome** and **click it open**
so the post itself is on screen — not the profile grid or feed with the post's URL merely
in the address bar. Then:

```bash
"${SKILL_DIR}/scripts/capture/capture-carousel.sh"
```

This takes no duration. It reuses the reel path's window detection, crop geometry and
on-device Vision OCR, then replaces the video recording with **one screenshot per slide**.
It rewinds to slide 1 first (a shared `?img_index=N` link opens mid-carousel), screenshots
each slide, clicks the post's own "Next" control, and stops when that control disappears —
which is how it knows it reached the end, with no slide count to supply. It prints
`CAPTURE_DIR=<path>` and `slides: <n>` on success.

If the Next control can't be driven — Chrome's "Allow JavaScript from Apple Events" is off,
or Instagram renamed it — it falls back to prompting the user to click through each slide
manually. Same capture, slower.

**Why advancing the slides is inside the acquisition rule.**
[`docs/capture/CONTRACT.md`](../../../docs/capture/CONTRACT.md)'s stated test is *"who
initiated the request to Meta's servers"*, and the answer here is nobody: the user opened
the post themselves, Instagram already delivered and preloaded the slides into the page,
and clicking Next renders images the browser is holding in memory. The prohibited row this
superficially resembles — "scripting the play button on a page **a script opened**" — is
about a script driving a whole session unattended, opening URLs and walking a list. That is
a different act from advancing a post a human opened and is sitting in front of.

What remains prohibited, and is deliberately not implemented: opening the post URL
ourselves, logging in, walking a list of posts, and reading the slide image URLs out of the
DOM to download them (an automated fetch to Meta's CDN). The human opens the post; the
script only advances and records what is already on their screen.

What you get:

- `frame_001.jpg … frame_NNN.jpg` — one image per slide, in the order captured.
- `frame_001.txt … frame_NNN.txt` — **per-slide OCR, one file per slide.** This is the
  important difference from the reel path, and it is deliberate: the slide boundary is the
  only signal telling you whether you're looking at one recipe or several (see below), so
  it's preserved on disk rather than flattened.
- `onscreen.txt` — every slide's OCR concatenated with `--- frame_NNN ---` delimiters, for
  when you want to read it all at once. **Not deduped**, unlike the reel path's
  `onscreen.clean.txt`: `dedupe-loop.mjs` exists because a reel *loops* and repeats itself,
  whereas distinct slides are not repetitions. Folding "1 cup oats" on slide 2 into the same
  line on slide 5 would silently merge two different recipes.
- `caption.txt` — the caption as exact text, same `og:description` read as the reel path,
  same caveats. Often absent on a carousel reached by in-app navigation (the SPA doesn't
  always re-render the meta tag) — the per-slide OCR is the fallback, and since the crop
  includes the caption panel it usually captured the caption anyway.
- `cover.jpg` — a copy of slide 1. Unlike a reel (where `capture.sh` samples a third of the
  way in to avoid a title card), a carousel's first slide is the cover the creator chose.

**One recipe or several? — decide this before structuring, it changes the output.** A
carousel is used both ways, and the two are easy to tell apart once you read the slides:

- **N recipes, one per slide** — each slide is self-contained, with its own dish name and
  its own ingredient list. Common for "5 lunchbox ideas" / "iron-rich baby meals" round-up
  posts. Save these as **separate recipes**, one `save_recipe` call each, each with its own
  title and its own `frame_NNN.jpg` as the thumbnail. Do not concatenate them into one
  recipe with 30 ingredients — that recipe is not cookable and matches nothing.
- **One recipe across many slides** — slide 1 is a title/hero, later slides carry
  ingredients then method, and no slide stands alone. Save as **one recipe**, exactly like a
  reel.
- **Ambiguous** — if some slides are recipes and others are filler (a "save this post" call
  to action, a promo card), extract the real ones and ignore the filler. If you genuinely
  can't tell whether it's one recipe or several, ask the user rather than guessing; the
  wrong choice is expensive to undo once saved.

Run the Step 0.5 dedup check per recipe you're about to save, not once for the post — N
recipes from one carousel are N separate library entries, and re-running a capture must not
create duplicates of any of them. They share a `sourceUrl`, so match on title as well.

**If the script says the post isn't open**, it checked the page and found the feed/profile
grid rather than the post. Ask the user to click the post open — don't retry blindly, and
don't fall back to capturing anyway: a screenshot of the feed OCRs into a dozen strangers'
captions that read exactly like real evidence.
