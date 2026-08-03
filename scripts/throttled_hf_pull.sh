#!/usr/bin/env bash
# Rate-limited HuggingFace pull.
#
# `hf download` has no rate limit and a single connection saturates the uplink.
# On 2026-07-31 a 53 Mbit/s pull put ask./chat./atticus. into intermittent 530s
# via bufferbloat — the agents were healthy, their replies just lost the race to
# Cloudflare's timeout. Shaping below line capacity keeps the buffer from filling.
#
#   ./throttled_hf_pull.sh <repo> <dest> [rate] [prefix]
#
# rate is a curl --limit-rate value. prefix, if given, restricts the pull to
# files under that path — repos often ship several quants and you want one.
#
# Sequential on purpose: one stream at a known cap beats N streams sharing one.
# Resumes with curl -C -, and skips files already at their published size, so it
# is safe to stop and re-run at any point.
set -uo pipefail

REPO="${1:?usage: throttled_hf_pull.sh <repo> <dest> [rate]}"
DEST="${2:?missing dest}"
RATE="${3:-4M}"
PREFIX="${4:-}"

mkdir -p "$DEST"
echo "  repo $REPO → $DEST   cap $RATE${PREFIX:+   only $PREFIX}"

LIST=$(curl -4 -sf -m 60 "https://huggingface.co/api/models/${REPO}?blobs=true") || {
  echo "  ERROR: could not fetch file list"; exit 1; }

python3 -c "
import json,sys
d=json.loads(sys.stdin.read())
for s in d.get('siblings',[]):
    print(f\"{s['rfilename']}\t{s.get('size') or 0}\")
" <<<"$LIST" | while IFS=$'\t' read -r name size; do
    [ -z "$name" ] && continue
    if [ -n "$PREFIX" ]; then case "$name" in "$PREFIX"*) ;; *) continue ;; esac; fi
    out="$DEST/$name"
    have=$(stat -c%s "$out" 2>/dev/null || echo 0)
    if [ "$size" -gt 0 ] && [ "$have" -eq "$size" ]; then
        continue                                   # already complete
    fi
    mkdir -p "$(dirname "$out")"
    printf "  %-52s %6.1f GB " "$name" "$(echo "$size/1000000000" | bc -l)"
    if curl -4 -sfL -C - --limit-rate "$RATE" --retry 5 --retry-delay 10 \
         -o "$out" "https://huggingface.co/${REPO}/resolve/main/${name}"; then
        echo "ok"
    else
        echo "FAILED (will resume on re-run)"
    fi
done

echo "  done — $(du -sh "$DEST" | cut -f1) on disk"
