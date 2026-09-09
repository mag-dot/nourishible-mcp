#!/usr/bin/env bash
# Capture one operator-opened, operator-played Instagram post and emit a manifest.
# This wrapper intentionally does not navigate, log in, press play, or set AUTO_YES.
set -euo pipefail

if [[ "${OSTYPE:-}" != darwin* ]]; then
  echo "This worker capture adapter requires macOS Screen Recording." >&2
  exit 2
fi

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 <source-url> <capture-dir> [seconds]" >&2
  exit 2
fi

SOURCE_URL="$1"
OUT_DIR="$2"
SECONDS="${3:-45}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CAPTURE="$ROOT/skills/recipe-nourishible/scripts/capture/capture-only.sh"

echo "Open this exact post in your normal Chrome profile and play it yourself:"
echo "  $SOURCE_URL"
echo "The preview confirmation is mandatory. This worker will not open the link or press play."
read -r -p "Have you personally opened and played this exact post? [y/N] " CONFIRM
if [[ "$CONFIRM" != "y" && "$CONFIRM" != "Y" ]]; then
  echo "Capture cancelled; no browser action was taken."
  exit 0
fi

unset AUTO_YES
"$CAPTURE" "$SECONDS" "$OUT_DIR"
PYTHONPATH="$ROOT/worker${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m nourishible_worker manifest "$OUT_DIR" "$SOURCE_URL" --out "$OUT_DIR/worker-manifest.json"
echo "WORKER_MANIFEST=$OUT_DIR/worker-manifest.json"
