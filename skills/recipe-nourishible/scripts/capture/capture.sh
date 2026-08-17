#!/usr/bin/env bash
# Capture a reel playing on your own screen, then extract text from it.
#
# WHY THIS EXISTS: Instagram's terms forbid automated fetching of post media.
# Recording what is already rendered on your screen is ordinary use of the app —
# you played it, nothing automated touched Meta's servers. See docs/RESEARCH.md.
#
# Usage:  ./scripts/capture.sh [seconds] [outdir]
#
# AUDIO CAVEAT: macOS has no system-audio capture device. Without BlackHole or
# Loopback installed, `-i "3:0"` records the MICROPHONE, not the app's audio —
# which means speaker output picked up by the mic, or silence if muted. The
# script detects this and tells you which case you are in rather than producing
# a confidently empty transcript.

set -euo pipefail

SECS="${1:-30}"
OUT="${2:-/tmp/ig-capture}"
MODEL="${WHISPER_MODEL:-$HOME/.whisper-models/ggml-base.en.bin}"
# ~/.local/bin/ocr is a permanent path — setup.py compiles ocr.swift there,
# not to /tmp, since macOS wipes /tmp on every reboot and a silently-missing
# OCR binary is a much worse failure than a slow rebuild would have been.
OCR_BIN="${OCR_BIN:-$HOME/.local/bin/ocr}"

mkdir -p "$OUT"
rm -f "$OUT"/frame_*.jpg "$OUT"/*.wav "$OUT"/*.mp4 "$OUT"/*.txt 2>/dev/null || true

# --- pick capture devices -----------------------------------------------------
# `ffmpeg -list_devices` ALWAYS exits non-zero (it has no real input), so every
# command reading it must be guarded — under `set -euo pipefail` an unguarded
# pipeline kills the script silently, mid-setup, with no error shown.
DEVICES="$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1 || true)"

# SCREEN_IDX may be set by the caller (grab.sh works out which display the
# reel is on); only auto-detect when it was not.
if [[ -z "${SCREEN_IDX:-}" ]]; then
  SCREEN_IDX="$(printf '%s\n' "$DEVICES" \
    | awk '/AVFoundation video devices/,/AVFoundation audio devices/' \
    | grep -i 'capture screen' | head -1 | sed -E 's/.*\[([0-9]+)\].*/\1/' || true)"
fi
SCREEN_IDX="${SCREEN_IDX:-3}"

# Prefer a virtual loopback device if one is installed — that captures true
# system audio. Otherwise fall back to the default input (microphone).
AUDIO_IDX="$(printf '%s\n' "$DEVICES" \
  | sed -n '/AVFoundation audio devices/,$p' \
  | grep -iE 'blackhole|loopback|soundflower|aggregate' | head -1 \
  | sed -E 's/.*\[([0-9]+)\].*/\1/' || true)"

if [[ -n "$AUDIO_IDX" ]]; then
  AUDIO_MODE="system audio (virtual device $AUDIO_IDX) — true app sound"
else
  AUDIO_IDX=0
  AUDIO_MODE="MICROPHONE — no virtual audio device installed; this records room sound, not the app"
fi

echo "screen device : $SCREEN_IDX"
echo "audio device  : $AUDIO_IDX"
echo "audio mode    : $AUDIO_MODE"

# Warn when the system OUTPUT is raw BlackHole. Audio then routes to the
# virtual device only — the capture works but you hear nothing, which reads
# as "the script is broken" mid-take. A Multi-Output Device fixes it.
if command -v SwitchAudioSource >/dev/null 2>&1; then
  CURRENT_OUT="$(SwitchAudioSource -c -t output 2>/dev/null || echo '')"
  if [[ "$CURRENT_OUT" == *"BlackHole"* ]]; then
    echo
    echo "!!! System output is '$CURRENT_OUT' — you will NOT hear the reel."
    echo "    Create a Multi-Output Device (Audio MIDI Setup) with both"
    echo "    speakers and BlackHole ticked, and select that instead."
  fi
fi

# Countdown so you can switch to the reel and start it playing. Recording
# straight away captures the terminal, not Instagram.
LEAD="${LEAD_SECONDS:-6}"
echo
echo ">>> Switch to the reel and press play. Recording starts in ${LEAD}s."
for ((i = LEAD; i > 0; i--)); do
  printf '\r    starting in %2ds ' "$i"
  sleep 1
done
printf '\r>>> RECORDING %ss — let it loop.            \n' "$SECS"

# Crop to the reel, not the whole desktop.
#
# This is not a nicety. A full-screen capture OCRs everything visible —
# terminal output, chat windows, browser tabs — which buries the ~10 lines of
# actual recipe text in hundreds of lines of desktop noise AND sweeps up
# private content (messages, contacts) into plain-text files. Cropping fixes
# the signal-to-noise problem and the privacy problem in one move.
#
# CROP is "width:height:x:y" in screen points. Default targets a portrait
# reel centred on a 1512-point-wide display.
CROP="${CROP:-}"
VF="format=yuv420p"
if [[ -n "$CROP" ]]; then
  VF="crop=${CROP},format=yuv420p"
  echo "crop         : $CROP"
else
  echo "crop         : NONE — capturing the full screen."
  echo "               Everything visible will be OCR'd, including other windows."
  echo "               Set CROP='w:h:x:y' to capture only the reel."
fi

# -pix_fmt/-vf are OUTPUT options. Before -i, ffmpeg negotiates them with the
# capture device (which offers only uyvy422/nv12/etc) and warns every run.
# The objc NSKVONotifying lines are harmless avfoundation noise.
ffmpeg -hide_banner -loglevel error -y \
  -f avfoundation -framerate 30 -capture_cursor 0 -i "${SCREEN_IDX}:${AUDIO_IDX}" \
  -t "$SECS" \
  -c:v libx264 -preset ultrafast -vf "$VF" \
  -c:a pcm_s16le -ar 16000 -ac 1 \
  "$OUT/capture.mp4" 2>&1 | grep -v 'NSKVONotifying\|not linked into application' || true

echo "recorded: $(du -h "$OUT/capture.mp4" | cut -f1)"

# --- audio -------------------------------------------------------------------
ffmpeg -hide_banner -loglevel error -y -i "$OUT/capture.mp4" \
  -vn -ar 16000 -ac 1 "$OUT/audio.wav" 2>/dev/null || true

LEVEL="silent"
if [[ -f "$OUT/audio.wav" ]]; then
  MEAN="$(ffmpeg -i "$OUT/audio.wav" -af volumedetect -f null /dev/null 2>&1 \
    | grep -oE 'mean_volume: -?[0-9.]+' | tail -1 | grep -oE '\-?[0-9.]+' || echo "-99")"
  echo "audio mean level: ${MEAN} dB"
  # Below about -45 dB is room tone / silence, not speech.
  if awk "BEGIN{exit !(${MEAN} > -45)}"; then LEVEL="audible"; fi
fi

if [[ "$LEVEL" == "audible" ]]; then
  echo ">>> transcribing..."
  whisper-cli -m "$MODEL" -f "$OUT/audio.wav" -nt 2>/dev/null | tee "$OUT/transcript.txt"
else
  echo ">>> NO USABLE AUDIO (level ${MEAN:-?} dB)."
  echo "    Either the reel was muted, or the mic did not pick up the speakers."
  echo
  echo "    For true system audio, BlackHole must be INSTALLED, not just"
  echo "    downloaded — 'brew install --cask' fetches the .pkg but the"
  echo "    driver only loads once the installer actually runs:"
  echo "      sudo installer -pkg /opt/homebrew/Caskroom/blackhole-2ch/*/BlackHole*.pkg -target /"
  echo "    Then make a Multi-Output Device (Audio MIDI Setup) with BOTH"
  echo "    your speakers and BlackHole ticked, and select it as output."
  : > "$OUT/transcript.txt"
fi

# --- on-screen text ----------------------------------------------------------
echo
echo ">>> extracting frames at 1fps and running OCR..."
ffmpeg -hide_banner -loglevel error -y -i "$OUT/capture.mp4" -vf fps=1 "$OUT/frame_%03d.jpg"

: > "$OUT/onscreen.txt"
if [[ -x "$OCR_BIN" ]]; then
  for f in "$OUT"/frame_*.jpg; do
    "$OCR_BIN" "$f" 2>/dev/null | awk '{$1=""; sub(/^ /,""); print}' >> "$OUT/onscreen.txt"
  done
  # Dedupe: consecutive frames repeat the same overlay text.
  sort -u "$OUT/onscreen.txt" -o "$OUT/onscreen.txt"
  echo "unique on-screen lines: $(wc -l < "$OUT/onscreen.txt" | tr -d ' ')"
else
  echo "OCR binary not found at $OCR_BIN — run setup.py, or build it manually with:"
  echo "  mkdir -p \"\$HOME/.local/bin\" && swiftc -O -o \"\$HOME/.local/bin/ocr\" scripts/capture/ocr.swift"
fi

# --- cover image -------------------------------------------------------------
# One frame, kept as the card's thumbnail. Taken from a third of the way in:
# reels open on a title card or a dark fade, so frame 1 is a poor cover.
#
# This is a LOCAL file. Hotlinking Instagram's CDN would break when their URLs
# rotate and would re-fetch from Meta every time a card renders.
if [[ -f "$OUT/capture.mp4" ]]; then
  COVER_AT="$(awk "BEGIN{printf \"%.1f\", $SECS/3}")"

  # The capture crop is deliberately wide so the caption header (and the
  # creator's handle) is inside it. That makes a full-frame cover mostly
  # browser chrome, so crop the cover to the VIDEO column only — the left
  # ~38%, which is where Instagram renders the reel in the web layout.
  COVER_VF="crop=iw*0.38:ih*0.62:iw*0.02:ih*0.20,scale=480:-2"
  ffmpeg -hide_banner -loglevel error -y -ss "$COVER_AT" -i "$OUT/capture.mp4" \
    -frames:v 1 -vf "$COVER_VF" "$OUT/cover.jpg" 2>/dev/null || true
  [[ -f "$OUT/cover.jpg" ]] && echo "cover: $(du -h "$OUT/cover.jpg" | cut -f1)"
fi

# --- collapse the loop -------------------------------------------------------
# Reels repeat until stopped, so a capture longer than the reel contains the
# same content 2-3x. Dedupe before extraction or ingredients triplicate.
echo
echo ">>> collapsing loop repetitions..."
if command -v node >/dev/null 2>&1; then
  # The script prints a JSON report then a human summary; show only the latter.
  node "$(dirname "$0")/dedupe-loop.mjs" "$OUT" 2>/dev/null \
    | grep -E '^(on-screen|transcript):' || true
fi

echo
echo "=== OUTPUT ==="
echo "video      : $OUT/capture.mp4"
echo "transcript : $OUT/transcript.txt"
echo "on-screen  : $OUT/onscreen.txt"
[[ -f "$OUT/transcript.clean.txt" ]] && echo "transcript (deduped) : $OUT/transcript.clean.txt"
[[ -f "$OUT/onscreen.clean.txt" ]] && echo "on-screen  (deduped) : $OUT/onscreen.clean.txt"
