# Xiaohongshu (XHS/RED/小红书) — reference

Read this when, and only when, the URL is a `xiaohongshu.com` or `xhslink.cn` link.
Step 1 of SKILL.md routes here.

Works on every platform this skill runs on, with no browser and no screen capture in the
loop at all — unlike either Instagram path. `yt-dlp` ships a real `XiaoHongShu` extractor (unlike Instagram/
TikTok), so this goes through `watch.py` the same way YouTube does; it auto-detects both
URL shapes (`xiaohongshu.com/explore/<id>`, `xiaohongshu.com/discovery/item/<id>`, and
`xhslink.cn/...` short links, which 302-redirect to the canonical form). Just run:

```bash
python3 "$WATCH_SCRIPT" "<xiaohongshu-or-xhslink-url>" --detail balanced --resolution 1024 --out-dir "${OUT_DIR:-}"
```

**A large share of XHS recipe content is a photo/图文 note, not a video** — a sequence of
images plus a text description, no video/audio at all. `watch.py` probes the note first
and branches automatically:

- **Photo/图文 note** (no video stream — common for recipe cards, ingredient-list graphics,
  step-by-step photo sequences): downloads every image in the carousel instead of video
  frames. The report you get back has no transcript and no frame timestamps — every step's
  `timestampSeconds` is `null` for this note type, not an evidence gap to chase. The note's
  **description is the caption-text equivalent of Instagram's `caption.txt`**: treat it as a
  first-class source per Step 2 — it very often carries the complete ingredient list and
  numbered steps as plain text, sometimes more complete than any single image. Read every
  image path the report lists, same as you'd Read video frames.
- **Video note**: proceeds exactly like the YouTube path from here — same `--detail`/
  `--resolution`/`--start`/`--end`/`--timestamps` flags, same transcript-cue pass, same
  Whisper fallback if the note has no native captions (most XHS videos don't; expect to
  fall back to Whisper on audio far more often than on YouTube).

**Known limits, tested 19 Aug 2026 against one real photo-note share link:**

- The tested link needed no login/cookies at all — public XHS content downloaded cleanly
  with a bare, anonymous `yt-dlp` request, unlike Instagram. This has **not** been verified
  against a currently-live video note (the one plausible test URL available — from
  `yt-dlp`'s own extractor test suite — now returns empty formats/thumbnails, most likely
  because the note itself has since been deleted, not because of an extraction failure).
  Treat the video-note path as implemented-by-construction (identical code path to
  YouTube) rather than independently verified end-to-end.
- Real XHS share links carry an `xsec_token` query param tied to how the link was shared;
  a bare note-id URL with no token attached may fail to load content even for a public
  note. Always use the actual link the user pasted (or its yt-dlp-resolved canonical form)
  rather than stripping query params down to just the note id before downloading —
  stripping to the bare id is fine for the Step 0.5 dedup *comparison*, not for the
  request itself.
- If a note does turn out to need a login (private content, or XHS tightens anonymous
  access later), there is currently no cookie/local-capture fallback for XHS the way there
  is for Instagram — tell the user plainly rather than attempting one that doesn't exist.
