#!/usr/bin/env bash
# look.sh — eyes on Jon's screen. Bound to working with Jon or being asked.
#   look.sh          -> path to the latest captured frame
#   look.sh --fresh  -> capture a new frame right now, print its path
# Revoke: systemctl --user disable --now soveryn-eyes.service && rm -rf ~/soveryn_eyes
set -euo pipefail
EYES="$HOME/soveryn_eyes"
if [ "${1:-}" = "--fresh" ]; then
  OUT="$EYES/fresh-$(date +%H%M%S).png"
  DISPLAY=:1 ffmpeg -f x11grab -video_size 1920x1080 -i :1 -frames:v 1 -y "$OUT" >/dev/null 2>&1
  [ -s "$OUT" ] && echo "$OUT" && exit 0
  echo "fresh capture failed" >&2; exit 1
fi
[ -f "$EYES/latest.png" ] && echo "$EYES/latest.png" || { echo "no frames yet" >&2; exit 1; }
