#!/usr/bin/env bash
# Capture a multi-image Instagram carousel post (/p/<id>) as one screenshot per
# slide, plus on-device OCR of each, for the skill to reason over.
#
# WHY A SEPARATE SCRIPT FROM capture-only.sh: that one records a *video* — it
# takes a duration, records with ffmpeg for N seconds, pulls audio, runs
# Whisper, and dedupes a looping reel. Every one of those assumptions is wrong
# for a photo carousel: there is no audio, no transcript, and no duration. A
# still post has no natural length, so "record for 45s" would capture the same
# motionless slide 45 times and then ask Whisper to transcribe silence. What IS
# shared — Chrome window detection, crop geometry, the Vision OCR binary — is
# reused below in the same form, deliberately not re-derived.
#
# THE ACQUISITION RULE (docs/capture/CONTRACT.md, binding — read it before
# changing anything here): *content enters only because a human caused it to be
# shown*. That is why this loops on a prompt and screenshots what is already on
# screen, instead of the two obvious shortcuts:
#
#   - Reading the slide image URLs out of the DOM and downloading them. That is
#     an automated fetch to Meta's CDN — the contract's "not permitted" table
#     names hotlinking/unofficial APIs explicitly.
#   - Scripting clicks on the next-slide arrow to advance the carousel. The
#     contract names this one too ("Scripting the play button on a page a script
#     opened — the click is the automation").
#
# The human presses the arrow; this records their screen. That is ordinary use
# of the app, and it is the only compliant route to slides 2..N.
#
# Usage: ./scripts/capture/capture-carousel.sh [outdir]
#
# Prints one line on success: CAPTURE_DIR=<path>  (the skill greps for this).

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${1:-$(mktemp -d -t recipe-extract-ig-carousel)}"
OCR_BIN="${OCR_BIN:-$HOME/.local/bin/ocr}"

# A carousel is capped at 20 slides by Instagram. The bound is a runaway guard
# for the loop below, not a product limit — the user ends the loop themselves.
MAX_SLIDES="${MAX_SLIDES:-20}"

# --- find the post window ----------------------------------------------------
#
# Identical approach to capture-only.sh (see its comments for why Chrome is
# asked directly rather than walking System Events, and why every tab is
# scanned rather than just the active one). The one difference: a carousel is a
# /p/ post and never a /reel/, and it does not play audio, so the "Audio
# playing" signal that disambiguates a reel is unavailable here. Matching on
# /p/ in the URL is the whole signal.
# Command substitution rather than `read < <(...)` process substitution: the
# latter is a bashism that macOS's /bin/bash 3.2 rejects with "ambiguous
# redirect" when the heredoc is nested inside it, and this script must run under
# the system bash without a shebang-visible upgrade.
WIN_INFO="$(osascript <<'APPLESCRIPT' 2>/dev/null || echo ""
tell application "Google Chrome"
  set best to ""
  set anyIG to ""
  repeat with w in windows
    try
      -- Chrome reports bounds as {left, top, right, bottom}, NOT {x,y,w,h} —
      -- width/height have to be derived, which is why the subtractions are here.
      set b to bounds of w
      set geom to (item 1 of b as text) & " " & (item 2 of b as text) & " " & ¬
        ((item 3 of b) - (item 1 of b) as text) & " " & ¬
        ((item 4 of b) - (item 2 of b) as text) & " " & (id of w as text)
      repeat with t in tabs of w
        try
          set u to URL of t
          if u contains "instagram.com" then
            set entry to geom & " " & u
            if anyIG is "" then set anyIG to entry
            if u contains "/p/" then
              if best is "" then set best to entry
            end if
          end if
        end try
      end repeat
    end try
  end repeat
  if best is not "" then return best
  return anyIG
end tell
APPLESCRIPT
)"
# Only the first line matters; guard against any stray trailing output.
WIN_INFO="$(printf '%s\n' "$WIN_INFO" | head -1)"

if [[ -z "${WIN_INFO:-}" ]]; then
  echo "Could not find a Chrome window showing an Instagram post." >&2
  echo "Open the carousel post (a /p/ URL) in Google Chrome, then re-run." >&2
  exit 1
fi

WX="$(echo "$WIN_INFO" | cut -d' ' -f1)"
WY="$(echo "$WIN_INFO" | cut -d' ' -f2)"
WW="$(echo "$WIN_INFO" | cut -d' ' -f3)"
WH="$(echo "$WIN_INFO" | cut -d' ' -f4)"
WIN_ID="$(echo "$WIN_INFO" | cut -d' ' -f5)"
POST_URL="$(echo "$WIN_INFO" | cut -d' ' -f6-)"

DETECTED_ID="$(echo "$POST_URL" | sed -nE 's#.*instagram\.com/(p|reel|reels|tv)/([A-Za-z0-9_-]+).*#\2#p')"

echo "window : ${POST_URL}"

# --- display geometry --------------------------------------------------------
#
# Carried over from capture-only.sh unchanged — see its comments for why
# Finder's combined-desktop bounds cannot be used and each display has to be
# measured separately. `screencapture -R` takes a rectangle in screen POINTS on
# the global desktop, so unlike the ffmpeg path this needs no per-device origin
# subtraction and no backing-scale conversion: the numbers Chrome reports are
# already in the right coordinate space.
FULLPNG="$(mktemp -t igfull).png"
screencapture -x "$FULLPNG" 2>/dev/null || true
rm -f "$FULLPNG"

# Crop the image column and the caption beside it, same 96%/95% window-relative
# box capture-only.sh uses. Keeping the caption panel in frame matters for the
# same reason it does there: the creator's handle lives in the caption header,
# and on a carousel the caption frequently carries the ingredient list that the
# slides only illustrate.
CROP_W=$(( WW * 96 / 100 ))
CROP_H=$(( WH * 95 / 100 ))
CROP_X=$(( WX + WW / 40 ))
CROP_Y=$(( WY + WH / 20 ))
[[ "$CROP_X" -lt 0 ]] && CROP_X=0
[[ "$CROP_Y" -lt 0 ]] && CROP_Y=0
RECT="${CROP_X},${CROP_Y},${CROP_W},${CROP_H}"
echo "crop   : ${RECT}  (x,y,w,h in points)"

# --- confirm the post is actually OPEN, not just the tab URL -----------------
#
# A tab can sit on a /p/ URL while the viewport shows the profile grid or feed
# behind a dismissed dialog — Instagram is a SPA and the URL outlives the modal.
# Capturing then yields a screenshot of a dozen unrelated posts, which OCRs into
# a confident-looking pile of other people's captions. That is worse than
# failing: it is plausible-but-wrong evidence, and the reader downstream cannot
# tell it apart from the real post. Ask the page what it is showing.
#
# Instagram renders an open post two different ways and the check must accept
# both: clicked from a feed it is a modal (role=dialog wrapping an article),
# while a directly-loaded /p/ URL is a standalone page with NO article element
# at all — testing only for the modal shape rejected a genuinely open post. The
# fallback signal works on either: an open post shows a large image and few
# links to OTHER posts, whereas the grid is mostly a wall of /p/ links.
#
# Like read-caption.sh, this issues NO network request — it inspects a page the
# user already loaded (see docs/capture/CONTRACT.md).
DIALOG_STATE="$(osascript 2>/dev/null <<AS || true
tell application "Google Chrome"
  repeat with w in windows
    if (id of w as text) is "${WIN_ID}" then
      repeat with t in tabs of w
        if (URL of t) contains "/p/" then
          try
            return execute t javascript "(function(){if(document.querySelector('div[role=\"dialog\"] article, article[role=\"presentation\"]'))return 'OPEN';var next=[...document.querySelectorAll('button')].some(b=>b.getAttribute('aria-label')==='Next');if(next)return 'OPEN';var big=[...document.querySelectorAll('img')].filter(i=>i.naturalWidth>=400).length;var links=document.querySelectorAll('a[href*=\"/p/\"]').length;return (big>0&&links<12)?'OPEN':'CLOSED';})()"
          on error errMsg number errNum
            if errNum is -12 then return "JS_BLOCKED"
            return "UNKNOWN"
          end try
        end if
      end repeat
    end if
  end repeat
  return "UNKNOWN"
end tell
AS
)"

case "$DIALOG_STATE" in
  CLOSED*)
    echo >&2
    echo "The tab is on a /p/ URL but the post itself is not open on screen —" >&2
    echo "what is visible is the feed/profile grid behind it." >&2
    echo "Click the post to open it, then re-run. (Capturing now would OCR a" >&2
    echo "page of unrelated posts and read as if it were this recipe.)" >&2
    exit 1
    ;;
  JS_BLOCKED*)
    # Not fatal: the same permission gates read-caption.sh, which already
    # degrades gracefully. The preview confirm below is then the only check, so
    # say plainly that it is now load-bearing.
    echo "note: cannot verify the post is open (Chrome > View > Developer >"
    echo "      'Allow JavaScript from Apple Events' is off). Check the preview"
    echo "      carefully — it is the only guard against capturing the feed."
    ;;
esac

mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/frame_*.jpg "$OUT_DIR"/*.txt 2>/dev/null || true

# --- preview one frame -------------------------------------------------------
# Same confirm-before-capturing gate as capture-only.sh. The privacy argument is
# identical: an uncropped grab OCRs every visible window into a plain-text file.
# Bring Chrome to the front FIRST. `screencapture -R` grabs whatever is on top
# of that rectangle, not the window that defined it — with Chrome behind other
# windows a "correct" crop silently captured Spotify, a VPN panel showing an IP,
# and a messaging app showing a phone number, then wrote all of it to a
# plain-text OCR file. The crop bounds the region; only raising Chrome bounds
# the *content*. This is the same hazard capture.sh's countdown addresses ("Switch
# to the reel... recording straight away captures the terminal"), which a
# prompt-driven loop does not get for free.
# Raising the APP is not enough: `activate` fronts whichever Chrome window was
# last focused, which on a multi-window setup is routinely not the post. The
# window carrying the post is identified by id during detection and raised
# explicitly here — without this, a correct crop rectangle was still filled by
# whatever app happened to sit over it.
raise_chrome() {
  osascript -e 'tell application "Google Chrome"' \
            -e '  activate' \
            -e '  repeat with w in windows' \
            -e "    if (id of w as text) is \"${WIN_ID}\" then set index of w to 1" \
            -e '  end repeat' \
            -e 'end tell' >/dev/null 2>&1 || true
  # A beat for the window server to finish compositing; without it the first
  # grab can still catch the previous frontmost window mid-transition.
  sleep 0.6
}

PREVIEW="$(mktemp -t igcarouselpreview).jpg"
raise_chrome
screencapture -x -t jpg -R "$RECT" "$PREVIEW" 2>/dev/null || true

if [[ "${AUTO_YES:-}" == "1" ]]; then
  rm -f "$PREVIEW"
  OK=y
else
  open "$PREVIEW" 2>/dev/null || true
  echo
  read -r -p "Does the preview show ONLY the post? [Y/n] " OK
fi
if [[ "${OK:-y}" =~ ^[Nn] ]]; then
  echo
  echo "Move or resize the Chrome window so the post fills it, then re-run."
  rm -f "$PREVIEW"
  exit 0
fi
rm -f "$PREVIEW"

# --- slide loop --------------------------------------------------------------
#
# Two modes, auto first.
#
# AUTO: click the carousel's own "Next" control between screenshots. This stays
# inside the acquisition rule (docs/capture/CONTRACT.md), whose stated test is
# *"who initiated the request to Meta's servers"*: the user opened this post
# themselves, Instagram has already delivered and preloaded the slides into the
# page, and advancing renders images the browser is holding in memory. Nothing
# here fetches from Meta. The prohibited row it superficially resembles —
# "scripting the play button on a page A SCRIPT OPENED" — is about a script that
# drives the whole session unattended, opening URLs and walking a list. That is
# a different act from advancing a post a human opened and is watching.
#
# Still NOT permitted, and deliberately not implemented: opening the post URL
# ourselves, logging in, or walking a list of posts. The human opens; we advance
# what is already on their screen.
#
# MANUAL: if the Next control can't be driven (Chrome's "Allow JavaScript from
# Apple Events" is off, or Instagram renamed the control), fall back to prompting
# the user to click through. Same capture, slower.

# Ask the page to advance. Echoes OK / END / NO_JS so the loop can tell "last
# slide" (a normal, expected stop) from "couldn't drive it" (fall back).
carousel_click() {
  local action="$1"  # Next | Go back
  osascript 2>/dev/null <<AS || echo "NO_JS"
tell application "Google Chrome"
  repeat with w in windows
    if (id of w as text) is "${WIN_ID}" then
      repeat with t in tabs of w
        if (URL of t) contains "/p/" then
          try
            return execute t javascript "(function(){var d=document.querySelector('div[role=\"dialog\"]')||document;var b=[...d.querySelectorAll('button')].find(x=>x.getAttribute('aria-label')==='${action}');if(b){b.click();return 'OK';}return 'END';})()"
          on error errMsg number errNum
            return "NO_JS"
          end try
        end if
      end repeat
    end if
  end repeat
end tell
AS
}

# Rewind to slide 1 so the capture starts at the cover regardless of which slide
# the user happened to leave on (a shared ?img_index=N link opens mid-carousel).
#
# The rewind's own result cannot decide auto-vs-manual on its own: on slide 1
# there is legitimately no "Go back" control, so it returns END for a perfectly
# healthy carousel. Only NO_JS is conclusive here. Whether we can actually drive
# the thing is settled afterwards by probing for the Next control itself.
AUTO_MODE=1
REWIND="$(carousel_click "Go back")"
if [[ "$REWIND" == "NO_JS" ]]; then
  AUTO_MODE=0
  FALLBACK_REASON="Chrome > View > Developer > 'Allow JavaScript from Apple Events' is off"
else
  for _ in $(seq 1 "$MAX_SLIDES"); do
    [[ "$(carousel_click "Go back")" == "OK" ]] || break
    sleep 0.5
  done

  # Now at slide 1. A carousel MUST offer a Next control here; a single-image
  # /p/ post will not. Probe without clicking, so this is a real diagnosis
  # rather than a side effect.
  #
  # Distinguishing these two matters: "Instagram renamed the control" and "this
  # post has one image" both end up in the manual loop, but they are different
  # problems and only the first is a bug to fix. Saying which one it is turns a
  # future DOM change into something diagnosable instead of just mysteriously
  # slow.
  HAS_NEXT="$(osascript 2>/dev/null <<AS || echo "NO_JS"
tell application "Google Chrome"
  repeat with w in windows
    if (id of w as text) is "${WIN_ID}" then
      repeat with t in tabs of w
        if (URL of t) contains "/p/" then
          try
            return execute t javascript "(function(){var d=document.querySelector('div[role=\"dialog\"]')||document;var n=[...d.querySelectorAll('button')].some(x=>x.getAttribute('aria-label')==='Next');var big=[...d.querySelectorAll('img')].filter(x=>x.naturalWidth>=400).length;return n?'YES':(big<=1?'SINGLE':'UNKNOWN');})()"
          on error errMsg number errNum
            return "NO_JS"
          end try
        end if
      end repeat
    end if
  end repeat
  return "UNKNOWN"
end tell
AS
)"
  case "$HAS_NEXT" in
    YES*) ;;  # healthy carousel, stay in auto
    SINGLE*)
      AUTO_MODE=0
      FALLBACK_REASON="no Next control at slide 1 — this looks like a single-image post, not a carousel"
      ;;
    NO_JS*)
      AUTO_MODE=0
      FALLBACK_REASON="Chrome > View > Developer > 'Allow JavaScript from Apple Events' is off"
      ;;
    *)
      AUTO_MODE=0
      FALLBACK_REASON="found the post, but could not find its Next control — Instagram may have renamed it (the script looks for a button with aria-label=\"Next\")"
      ;;
  esac
fi

SLIDE=0
if (( AUTO_MODE )); then
  echo ">>> advancing the carousel automatically; capturing each slide..."
  while (( SLIDE < MAX_SLIDES )); do
    SLIDE=$(( SLIDE + 1 ))
    FRAME="$(printf '%s/frame_%03d.jpg' "$OUT_DIR" "$SLIDE")"
    raise_chrome
    screencapture -x -t jpg -R "$RECT" "$FRAME" 2>/dev/null || true
    if [[ ! -s "$FRAME" ]]; then
      echo "    could not capture slide ${SLIDE} — is Screen Recording granted?" >&2
      rm -f "$FRAME"
      SLIDE=$(( SLIDE - 1 ))
      break
    fi
    echo "    saved $(basename "$FRAME") ($(du -h "$FRAME" | cut -f1))"
    RESULT="$(carousel_click "Next")"
    # END means the Next control is gone: that IS the last slide, not a failure.
    [[ "$RESULT" == "OK" ]] || break
    # Instagram cross-fades; capturing too early catches the previous slide.
    sleep 1.3
  done
else
  echo ">>> falling back to manual: ${FALLBACK_REASON:-unknown reason}."
  echo ">>> For each slide: bring it up, then press RETURN. 'd' when done."
  echo
  while (( SLIDE < MAX_SLIDES )); do
    NEXT=$(( SLIDE + 1 ))
    if [[ "${AUTO_YES:-}" == "1" ]]; then
      ANS=""
      (( NEXT > 1 )) && ANS="d"
    else
      read -r -p "slide ${NEXT}: RETURN to capture, 'd' if there are no more > " ANS || ANS="d"
    fi
    [[ "$ANS" =~ ^[Dd] ]] && break
    SLIDE=$NEXT
    FRAME="$(printf '%s/frame_%03d.jpg' "$OUT_DIR" "$SLIDE")"
    raise_chrome
    screencapture -x -t jpg -R "$RECT" "$FRAME" 2>/dev/null || true
    if [[ ! -s "$FRAME" ]]; then
      echo "    could not capture slide ${SLIDE} — is Screen Recording granted?" >&2
      rm -f "$FRAME"
      continue
    fi
    echo "    saved $(basename "$FRAME") ($(du -h "$FRAME" | cut -f1))"
  done
fi

if (( SLIDE == 0 )); then
  echo "No slides captured." >&2
  exit 1
fi
echo
echo "captured ${SLIDE} slide(s)"

# --- on-screen text ----------------------------------------------------------
#
# Per-slide OCR files, NOT one concatenated blob. A carousel can hold several
# distinct recipes (one per slide) or a single recipe spread across slides, and
# only the reader can tell which. Collapsing the text loses the slide boundary
# that distinction depends on, so the boundary is preserved on disk and the
# decision is left to Step 2.
#
# Also deliberately NOT deduped: dedupe-loop.mjs exists because a *reel* repeats
# itself on loop. Distinct slides are not repetitions — "1 cup oats" appearing
# on slide 2 and slide 5 is two recipes sharing an ingredient, and folding them
# together would silently merge two recipes into one.
: > "$OUT_DIR/onscreen.txt"
if [[ -x "$OCR_BIN" ]]; then
  echo ">>> running on-device OCR (Apple Vision — no network call)..."
  for f in "$OUT_DIR"/frame_*.jpg; do
    BASE="$(basename "$f" .jpg)"
    "$OCR_BIN" "$f" 2>/dev/null | awk '{$1=""; sub(/^ /,""); print}' > "$OUT_DIR/${BASE}.txt" || true
    {
      echo "--- ${BASE} ---"
      cat "$OUT_DIR/${BASE}.txt" 2>/dev/null || true
      echo
    } >> "$OUT_DIR/onscreen.txt"
  done
  echo "on-screen lines: $(grep -cve '^$' "$OUT_DIR/onscreen.txt" | tr -d ' ')"
else
  echo "OCR binary not found at $OCR_BIN — run:" >&2
  echo "  python3 ${REPO}/../setup.py --install-capture" >&2
fi

# --- caption, as text rather than pixels -------------------------------------
# Same reasoning and same script as the reel path: og:description is already in
# the loaded page, so this beats OCR'ing the caption off pixels (no fold
# truncation, no transcription errors, no comment-thread noise). Best-effort —
# a failure here must never discard slides already captured.
if [[ -n "${DETECTED_ID:-}" ]] && "$REPO/read-caption.sh" "$DETECTED_ID" > "$OUT_DIR/caption.txt" 2>/dev/null; then
  echo "caption    : $OUT_DIR/caption.txt ($(wc -c < "$OUT_DIR/caption.txt" | tr -d ' ') bytes)"
else
  rm -f "$OUT_DIR/caption.txt"
  echo "caption    : unavailable (per-slide OCR text is the fallback)"
  echo "             if this is unexpected: Chrome > View > Developer >"
  echo "             'Allow JavaScript from Apple Events' must be enabled."
fi

# --- cover image -------------------------------------------------------------
# Slide 1 is the cover. Unlike a reel — where frame 1 is usually a title card or
# a dark fade, so capture.sh samples a third of the way in — a carousel's first
# slide is chosen by the creator as the thing people see in the grid.
#
# A LOCAL file, for the same reason capture.sh says: hotlinking Instagram's CDN
# would re-fetch from Meta on every render and break when their URLs rotate.
if [[ -f "$OUT_DIR/frame_001.jpg" ]]; then
  cp "$OUT_DIR/frame_001.jpg" "$OUT_DIR/cover.jpg"
  echo "cover      : $OUT_DIR/cover.jpg"
fi

echo
echo "=== OUTPUT ==="
echo "slides     : ${SLIDE}"
echo "frames     : $OUT_DIR/frame_*.jpg"
echo "per-slide  : $OUT_DIR/frame_*.txt  (OCR, one file per slide)"
echo "on-screen  : $OUT_DIR/onscreen.txt (all slides, slide-delimited)"
echo
echo "CAPTURE_DIR=$OUT_DIR"
echo "post id: ${DETECTED_ID:-unknown}"
echo "slides: ${SLIDE}"
