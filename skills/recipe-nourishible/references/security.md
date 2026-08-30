# Security & permissions — reference

Audit material: what this skill runs, what leaves the machine, and which OS permissions
each path asks for. Read before first use, or when a user asks what the skill does to
their machine. Not needed to run an extraction.

## What this skill does

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
- **For a Xiaohongshu photo/图文 note:** downloads the note's images directly from XHS's
  CDN (`sns-webpic-qc.xhscdn.com` and related `xhscdn.com` hosts) instead of a video — same
  "public data, direct request, written to the working directory" shape as the video path,
  just images instead of extracted frames.
- Reads/creates `~/.config/watch/.env` (mode `0600`) to store the Whisper API key(s) and a
  `SETUP_COMPLETE` marker.
- Calls the `save_recipe`/`update_recipe`/`set_recipe_thumbnail`/`list_my_recipes`/
  `get_my_recipe`/`search_recipes`/`get_recipe` nourishible tools (Step 6.5) once
  connected — these persist the structured recipe (and a thumbnail, if picked) to the
  user's real nourishible library. That's the point of Step 6.5, not a side effect to be
  surprised by.

**On the Instagram agent-controlled-browser path**, this skill asks for no system
permissions at all: it drives a Chrome the user already has open, through whatever browser
tooling the agent is configured with, and reads only the page the user themselves
navigated to. It takes screenshots of that tab and evaluates script in it to pause/seek
the already-playing `<video>`; it performs no navigation, no clicking, no form-filling, no
sign-in, and no requests to Instagram of its own. Nothing captured leaves the session
except the frames and caption text that feed Step 2/3, same as every other path.

**On the Instagram local-capture path** (`scripts/capture/`), this skill asks for real
system permissions the YouTube path never touches — worth being explicit about rather than
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
  see [`docs/capture/CONTRACT.md`](../../../docs/capture/CONTRACT.md) for why that distinction
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
- `scripts/watch.py` (entry point), `scripts/download.py` (yt-dlp wrapper — also handles
  Xiaohongshu note-type probing and photo/图文 image downloads), `scripts/frames.py`
  (ffmpeg frame extraction), `scripts/transcribe.py` (caption selection + Whisper
  orchestration), `scripts/whisper.py` (Groq/OpenAI clients), `scripts/config.py` (shared
  config helpers) — the YouTube and Xiaohongshu paths.
- `scripts/setup.py` — preflight/installer for both paths (`--check` plus a bare
  `setup.py` to install for YouTube, `--check-capture`/`--install-capture` for
  Instagram, gated separately so a
  YouTube-only user is never asked to install the Instagram half).
- `scripts/capture/` (`capture.sh`, `capture-only.sh`, `capture-carousel.sh`,
  `read-caption.sh`, `ocr.swift`, `dedupe-loop.mjs`) — the Instagram path;
  `capture-carousel.sh` is the still-image carousel variant of `capture-only.sh`. See Attribution below for where this came from,
  and [`docs/capture/CONTRACT.md`](../../../docs/capture/CONTRACT.md) before changing anything
  about how it acquires content.

Review all of the above before first use to verify behavior.

**A note on restricted environments:** some agents run in a sandbox with its own outbound
network allowlist (a cloud/managed execution environment, not this skill or nourishible).
If the source platform's domain, `xhscdn.com`, `api.groq.com`/`api.openai.com`, or the
nourishible MCP server itself isn't on that list, the relevant request is blocked at the
proxy before this skill's own logic ever runs — see "Blocked by this environment's own
network policy" under Failure modes above for how that should be handled and reported.
