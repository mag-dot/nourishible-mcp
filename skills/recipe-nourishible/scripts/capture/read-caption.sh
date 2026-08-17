#!/usr/bin/env bash
# Read an Instagram post's caption as TEXT, from the page the user already has open.
#
# WHY THIS EXISTS: the caption is real text in the DOM, not burned into the video.
# OCR'ing it off screen pixels was always the worse route — it truncates at the fold
# (a real capture cut off at exactly "This little bowl was made with:", losing the
# entire ingredient list), it introduces transcription errors ("1 tbso", "12 teaspoon
# salt" — a 24x salt overstatement in a baby-food context), and it sweeps in comment
# threads as noise. Reading og:description gets the complete caption, exactly as
# written, in one call.
#
# COMPLIANCE (docs/CONTRACT.md): this issues NO network request to Instagram. The
# page is already loaded and already rendered on the user's screen because they
# opened it; og:description is sitting in memory. This observes what is already
# there, exactly as screen capture does — it does not fetch anything.
#
# REQUIRES: Chrome > View > Developer > "Allow JavaScript from Apple Events".
# Without it Chrome refuses execute-javascript with error -12; this script detects
# that specific case and says so, rather than failing opaquely.
#
# Usage: ./read-caption.sh [post-url-substring]
#   With no argument, reads the first instagram.com/p|reel tab found.
#   Prints the caption to stdout. Exit 0 on success, 1 if JS is blocked,
#   2 if no matching tab, 3 if the tab has no caption.

set -euo pipefail

MATCH="${1:-}"

# og:description is Instagram's server-rendered summary and carries the full
# caption. Deliberately NOT scraping DOM class names — Instagram's are obfuscated
# and rotate. Deliberately NOT falling back to "longest text node on the page"
# either: that was tried and returned a hostile comment from the thread rather
# than the caption, which is exactly the kind of plausible-but-wrong data this
# pipeline must not produce.
RESULT="$(MATCH="$MATCH" osascript <<'APPLESCRIPT' 2>&1 || true
on run
  set matchStr to (system attribute "MATCH")
  tell application "Google Chrome"
    repeat with w in windows
      repeat with t in tabs of w
        set u to URL of t
        if (u contains "instagram.com/p/" or u contains "instagram.com/reel") then
          if matchStr is "" or u contains matchStr then
            try
              set og to execute t javascript "(function(){var m=document.querySelector('meta[property=\"og:description\"]');return m?m.getAttribute('content'):'';})()"
              if og is "" then return "NO_CAPTION"
              return "OK:" & og
            on error errMsg number errNum
              if errNum is -12 then return "JS_BLOCKED"
              return "ERROR:" & errMsg
            end try
          end if
        end if
      end repeat
    end repeat
  end tell
  return "NO_TAB"
end run
APPLESCRIPT
)"

case "$RESULT" in
  JS_BLOCKED*)
    echo "Chrome is blocking JavaScript from Apple Events." >&2
    echo "Enable it: Chrome menu > View > Developer > Allow JavaScript from Apple Events" >&2
    exit 1
    ;;
  NO_TAB*)
    echo "No Instagram post tab found in Chrome${MATCH:+ matching '$MATCH'}." >&2
    exit 2
    ;;
  NO_CAPTION*)
    echo "Tab found but it has no og:description caption." >&2
    exit 3
    ;;
  ERROR:*)
    echo "${RESULT#ERROR:}" >&2
    exit 1
    ;;
esac

# Strip the "OK:" sentinel and Instagram's own engagement preamble
# ("20K likes, 1,156 comments - mothers.2b on May 26, 2026: \"...\"") so what
# lands on stdout is the caption itself, not metadata wrapped around it.
printf '%s\n' "${RESULT#OK:}" \
  | sed -E 's/^[0-9,.KM]+ likes?, [0-9,.KM]+ comments? - [^:]*: "//' \
  | sed -E 's/"\.[[:space:]]*$//'
