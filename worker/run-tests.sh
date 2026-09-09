#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 -m unittest discover -s "$ROOT/worker/tests" -t "$ROOT/worker" -v
