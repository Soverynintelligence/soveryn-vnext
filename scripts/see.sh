#!/usr/bin/env bash
# see.sh — render a page and hand the screenshot to the seat that asked.
# THE rule this enforces (SOVERYN.md, 2026-09-22): no visual claim without
# reading the screenshot. "Looks good" without having run this is a guess.
#
#   scripts/see.sh <url-or-file> [out.png] [--width W] [--height H]
# Examples:
#   scripts/see.sh http://localhost:5001/command-center
#   scripts/see.sh demos/orrery/index.html /tmp/orrery.png --height 900
set -euo pipefail
TARGET="${1:?usage: see.sh <url-or-file> [out.png]}"
OUT="${2:-/tmp/see-$(date +%s).png}"
W="${3:-}"; H="${4:-}"
case "$TARGET" in
  http*|https*) URL="$TARGET" ;;
  *) URL="file://$(readlink -f "$TARGET")" ;;
esac
ARGS=(--headless=new --disable-gpu --hide-scrollbars
      "--screenshot=$OUT" "--window-size=${W:-1440},${H:-1000}")
BIN=""
for b in google-chrome chromium chromium-browser; do
  command -v "$b" >/dev/null 2>&1 && BIN="$b" && break
done
[ -z "$BIN" ] && { echo "no chrome/chromium on PATH" >&2; exit 2; }
timeout 30 "$BIN" "${ARGS[@]}" "$URL" >/dev/null 2>&1 || true
[ -s "$OUT" ] && echo "$OUT" || { echo "screenshot failed" >&2; exit 1; }
