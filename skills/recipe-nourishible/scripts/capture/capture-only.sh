#!/usr/bin/env bash
# One command: play the reel, run this, get raw evidence (frames + OCR +
# transcript) for the recipe-extract skill to reason over. This is grab.sh
# from ig-saved with the tail replaced: everything through the actual screen
# capture is identical (window detection, crop geometry, the preview
# confirm), but this stops there instead of running ig-saved's own
# extractor/catalog — the skill does that part itself, reading the frames
# and transcript directly (see recipe-extract/SKILL.md Step 2), the same
# way it already handles YouTube via watch.py.
#
# Usage: ./scripts/capture/capture-only.sh [seconds] [outdir]
#
# Prints one line on success: CAPTURE_DIR=<path>  (the skill greps for this).

set -euo pipefail

SECS="${1:-45}"
REPO="$(cd "$(dirname "$0")" && pwd)"
OUT_DIR="${2:-$(mktemp -d -t recipe-extract-ig)}"
MODEL="${WHISPER_MODEL:-$HOME/.whisper-models/ggml-base.en.bin}"
OCR_BIN="${OCR_BIN:-$HOME/.local/bin/ocr}"

# --- find the reel window ----------------------------------------------------
#
# Chrome reports a playing tab as "… – Audio playing" in the window title, and
# that is a far better signal than "first window returned". Taking the first
# window picked a YouTube tab on another display while the reel played
# unseen behind it — a wasted capture of entirely the wrong content.
#
# Preference order:
#   1. a window whose title says Audio playing AND mentions Instagram
#   2. any window mentioning Instagram
#   3. any window that says Audio playing
# Tiny toolbar/panel windows (height < 200) are skipped — Chrome reports
# several of those and they are never the content.
# Ask Chrome directly rather than walking System Events windows: it is far
# faster (System Events across several processes can hang for minutes) and it
# exposes the active tab's URL, which is a much better signal than a window
# title cluttered with "High memory usage".
read -r WIN_INFO < <(osascript <<'APPLESCRIPT' 2>/dev/null || echo ""
tell application "Google Chrome"
  set best to ""
  set anyIG to ""
  -- Scan EVERY tab, not just the active one: a reel can be playing in a
  -- background tab of a window whose active tab is something else. Checking
  -- only the active tab reported "no Instagram window" while one was open.
  repeat with w in windows
    try
      set b to bounds of w
      set geom to (item 1 of b as text) & " " & (item 2 of b as text) & " " & ¬
        ((item 3 of b) - (item 1 of b) as text) & " " & ¬
        ((item 4 of b) - (item 2 of b) as text)
      repeat with t in tabs of w
        try
          set u to URL of t
          if u contains "instagram.com" then
            set entry to geom & " " & u
            if anyIG is "" then set anyIG to entry
            -- a /p/ or /reel/ URL is an actual post, not the feed
            if (u contains "/p/") or (u contains "/reel") then
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
)

if [[ -z "${WIN_INFO:-}" ]]; then
  echo "Could not find a browser window playing Instagram."
  echo "Open the reel and press play, then re-run."
  exit 1
fi

WX="$(echo "$WIN_INFO" | cut -d' ' -f1)"
WY="$(echo "$WIN_INFO" | cut -d' ' -f2)"
WW="$(echo "$WIN_INFO" | cut -d' ' -f3)"
WH="$(echo "$WIN_INFO" | cut -d' ' -f4)"
POST_URL="$(echo "$WIN_INFO" | cut -d' ' -f5-)"
WNAME="$POST_URL"

# The post shortcode from the URL becomes the storage key, so a re-capture
# updates the same record instead of creating a duplicate.
DETECTED_ID="$(echo "$POST_URL" | sed -nE 's#.*instagram\.com/(p|reel|reels|tv)/([A-Za-z0-9_-]+).*#\2#p')"

# Per-display geometry.
#
# Finder's desktop bounds returns the COMBINED desktop across all monitors
# (3432 wide here), not the main display — using it made the scale compute as
# 3024/3432 = 0 and put the crop on the wrong screen entirely. system_profiler
# reports each display separately, including the logical "UI Looks like" size
# that Retina scaling is derived from.
DISP_INFO="$(system_profiler SPDisplaysDataType 2>/dev/null || true)"

# Main display physical width, from a full-screen grab (always the main one).
FULLPNG="$(mktemp -t igfull).png"
screencapture -x "$FULLPNG" 2>/dev/null
MAIN_PHYS_W="$(sips -g pixelWidth "$FULLPNG" 2>/dev/null | awk '/pixelWidth/{print $2}')"
rm -f "$FULLPNG"
MAIN_PHYS_W="${MAIN_PHYS_W:-3024}"

# Logical width of the main display: physical / backing scale. macOS Retina
# displays are 2x; an external 4K running a 1920-point UI is also 2x.
MAIN_LOG_W=$(( MAIN_PHYS_W / 2 ))

echo "window : ${WNAME}"

DEVICES="$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1 || true)"

# Multi-display: each screen is a separate avfoundation device, and crop
# coordinates are relative to THAT device's origin, not the global desktop.
# A window at x=1513 on a 1512-wide main display lives on screen 1, and
# capturing screen 0 records the wrong monitor entirely.
# macOS ships bash 3.2, which has no `mapfile`. Read into an array the
# portable way instead.
SCREENS=()
while IFS= read -r line; do
  [[ -n "$line" ]] && SCREENS+=("$line")
done < <(printf '%s\n' "$DEVICES" \
  | awk '/video devices/,/audio devices/' \
  | grep -i 'capture screen' | sed -E 's/.*\[([0-9]+)\] Capture screen ([0-9]+).*/\1 \2/')

SCREEN_IDX=""
DISPLAY_ORIGIN_X=0
SCALE=2

if [[ -n "${DISPLAY_INDEX:-}" ]]; then
  WANT_SCREEN="$DISPLAY_INDEX"
elif [[ "$WX" -ge "$MAIN_LOG_W" ]]; then
  # Window sits beyond the main display's logical width, so it is on screen 1.
  WANT_SCREEN=1
else
  WANT_SCREEN=0
fi

if [[ "$WANT_SCREEN" == "0" ]]; then
  DISPLAY_ORIGIN_X=0
  SCALE=$(( MAIN_PHYS_W / MAIN_LOG_W ))
else
  DISPLAY_ORIGIN_X="$MAIN_LOG_W"
  # Secondary display: physical from the second Resolution line, logical from
  # its "UI Looks like" line.
  SEC_PHYS_W="$(printf '%s\n' "$DISP_INFO" | grep -i 'Resolution:' | sed -n '2p' \
    | sed -E 's/.*Resolution: *([0-9]+).*/\1/' || true)"
  SEC_LOG_W="$(printf '%s\n' "$DISP_INFO" | grep -i 'UI Looks like' \
    | sed -E 's/.*UI Looks like: *([0-9]+).*/\1/' | head -1 || true)"
  SEC_PHYS_W="${SEC_PHYS_W:-3840}"
  SEC_LOG_W="${SEC_LOG_W:-1920}"
  [[ "$SEC_LOG_W" -gt 0 ]] && SCALE=$(( SEC_PHYS_W / SEC_LOG_W ))
fi
[[ "$SCALE" -lt 1 ]] && SCALE=1

for s in "${SCREENS[@]}"; do
  [[ "$(echo "$s" | cut -d' ' -f2)" == "$WANT_SCREEN" ]] && SCREEN_IDX="$(echo "$s" | cut -d' ' -f1)"
done
SCREEN_IDX="${SCREEN_IDX:-3}"
echo "display: screen $WANT_SCREEN (device $SCREEN_IDX, origin x=$DISPLAY_ORIGIN_X, ${SCALE}x)"

# Crop is relative to the chosen display's own origin, so subtract it before
# scaling to physical pixels.
REL_X=$(( WX - DISPLAY_ORIGIN_X ))
# Crop the video column AND the caption panel beside it.
#
# An earlier 55%-wide crop covered only the video, and cost real data: the
# creator's handle lives in the caption header, so every card came back with
# username null. Instagram's web layout puts the reel on the left and the
# caption/comments on the right, and the recipe itself is frequently in that
# caption — so both halves matter.
#
# The tradeoff is more desktop text reaching OCR when the window is small;
# the default-deny filter is what keeps that safe.
CROP_W=$(( WW * 96 / 100 * SCALE ))
CROP_H=$(( WH * 95 / 100 * SCALE ))
CROP_X=$(( (REL_X + WW / 40) * SCALE ))
CROP_Y=$(( (WY + WH / 20) * SCALE ))
[[ "$CROP_X" -lt 0 ]] && CROP_X=0
[[ "$CROP_Y" -lt 0 ]] && CROP_Y=0
CROP="${CROP_W}:${CROP_H}:${CROP_X}:${CROP_Y}"
echo "crop   : ${CROP}  (${SCALE}x scale)"
AUDIO_IDX="$(printf '%s\n' "$DEVICES" | sed -n '/audio devices/,$p' \
  | grep -iE 'blackhole|loopback|soundflower' | head -1 \
  | sed -E 's/.*\[([0-9]+)\].*/\1/' || true)"

if [[ -z "$AUDIO_IDX" ]]; then
  echo "audio  : MICROPHONE (no virtual device) — transcript will be noisy"
  AUDIO_IDX=0
else
  echo "audio  : system audio via device $AUDIO_IDX"
fi

# --- preview one frame -------------------------------------------------------
PREVIEW="$(mktemp -t igpreview).jpg"
ffmpeg -hide_banner -loglevel error -y -f avfoundation -framerate 30 -capture_cursor 0 \
  -i "$SCREEN_IDX" -frames:v 1 -vf "crop=${CROP}" "$PREVIEW" \
  2>&1 | grep -vE 'NSKVO|not linked|pixel format|uyvy|yuyv|nv12|rgb|bgr' || true

# AUTO_YES skips the interactive confirm — set by the queue server, which has
# no terminal to prompt on. The privacy backstop (default-deny OCR filtering)
# still applies, but a mis-crop will not be caught by a human here.
if [[ "${AUTO_YES:-}" == "1" ]]; then
  rm -f "$PREVIEW"
  OK=y
else
  open "$PREVIEW" 2>/dev/null || true
  echo
  read -r -p "Does the preview show ONLY the reel? [Y/n] " OK
fi
if [[ "${OK:-y}" =~ ^[Nn] ]]; then
  echo
  echo "Adjust manually and re-run capture.sh with your own rectangle:"
  echo "  CROP='w:h:x:y' ./scripts/capture/capture.sh $SECS"
  rm -f "$PREVIEW"
  exit 0
fi
rm -f "$PREVIEW"

# --- capture -----------------------------------------------------------------
mkdir -p "$OUT_DIR"
LEAD_SECONDS="${LEAD_SECONDS:-4}" CROP="$CROP" SCREEN_IDX="$SCREEN_IDX" \
  "$REPO/capture.sh" "$SECS" "$OUT_DIR" \
  2>&1 | grep -vE 'NSKVO|not linked|pixel format|uyvy|yuyv|nv12|0rgb|bgr0'

# --- caption, as text rather than pixels -------------------------------------
# Read the caption straight from the already-open page instead of OCR'ing it.
# OCR truncates at the fold — a real capture cut off at exactly "This little
# bowl was made with:", losing the whole ingredient list that followed. This
# gets the complete caption with no transcription errors and no comment-thread
# noise. Best-effort: a failure here (Chrome's Apple Events JS setting off, tab
# closed early) degrades to OCR-only, which is the pre-existing behaviour, so
# it must never abort the capture that already succeeded.
if [[ -n "${DETECTED_ID:-}" ]] && "$REPO/read-caption.sh" "$DETECTED_ID" > "$OUT_DIR/caption.txt" 2>/dev/null; then
  echo "caption    : $OUT_DIR/caption.txt ($(wc -c < "$OUT_DIR/caption.txt" | tr -d ' ') bytes)"
else
  rm -f "$OUT_DIR/caption.txt"
  echo "caption    : unavailable (OCR text in onscreen.clean.txt is the fallback)"
  echo "             if this is unexpected: Chrome > View > Developer >"
  echo "             'Allow JavaScript from Apple Events' must be enabled."
fi

echo
echo "CAPTURE_DIR=$OUT_DIR"
echo "post id: ${DETECTED_ID:-unknown}"
