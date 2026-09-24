#!/usr/bin/env bash
# Restore drill for operator secrets/state — Critic kill-list #2.
#
# An untested backup is hope. This restores the latest secrets bundle into a
# scratch dir and verifies SHA-256 against MANIFEST.txt — it does NOT overwrite
# live .env / tokens.
#
# Usage:
#   scripts/restore_secrets_drill.sh
#   scripts/restore_secrets_drill.sh /path/to/backups/2026-08-24
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
LOG_PREFIX="[secrets-drill $(date +%H:%M:%S)]"

if [ "${1:-}" != "" ]; then
    SNAP="$1"
else
    SNAP=$(ls -td "$BASE"/backups/20*-*-* 2>/dev/null | head -1 || true)
fi

if [ -z "${SNAP:-}" ] || [ ! -d "$SNAP/secrets" ]; then
    echo "$LOG_PREFIX ✗ FAIL: no secrets/ in snapshot (run backup_soveryn.sh first)" >&2
    exit 1
fi

SCRATCH=$(mktemp -d /tmp/soveryn-secrets-drill.XXXXXX)
trap 'rm -rf "$SCRATCH"' EXIT

echo "$LOG_PREFIX snapshot=$SNAP"
echo "$LOG_PREFIX scratch=$SCRATCH"
cp -a "$SNAP/secrets/." "$SCRATCH/"
chmod 700 "$SCRATCH"

MANIFEST="$SCRATCH/MANIFEST.txt"
if [ ! -f "$MANIFEST" ]; then
    echo "$LOG_PREFIX ✗ FAIL: MANIFEST.txt missing" >&2
    exit 1
fi

required=(soveryn_vnext.env canva_tokens.json eve_persona.md)
missing=0
for name in "${required[@]}"; do
    if [ ! -f "$SCRATCH/$name" ]; then
        echo "$LOG_PREFIX ✗ missing required $name"
        missing=1
    fi
done
if [ "$missing" -ne 0 ]; then
    exit 1
fi

# Verify hashes from manifest
while read -r line; do
    case "$line" in
        *.env\ sha256=*|*.json\ sha256=*|*.md\ sha256=*|*.toml\ sha256=*)
            name=${line%% *}
            expect=${line#*sha256=}
            expect=${expect%% *}
            got=$(sha256sum "$SCRATCH/$name" | awk '{print $1}')
            if [ "$got" != "$expect" ]; then
                echo "$LOG_PREFIX ✗ HASH MISMATCH $name" >&2
                exit 1
            fi
            echo "$LOG_PREFIX ✓ $name hash ok"
            ;;
    esac
done < "$MANIFEST"

# Sanity: Canva client id key present (not the value printed)
if ! grep -q 'SOVERYN_CANVA_CLIENT_ID=' "$SCRATCH/soveryn_vnext.env"; then
    echo "$LOG_PREFIX ⚠ soveryn_vnext.env has no SOVERYN_CANVA_CLIENT_ID (ok if unused)"
else
    echo "$LOG_PREFIX ✓ soveryn_vnext.env contains Canva keys (names only checked)"
fi

echo "$LOG_PREFIX ✓ PASS — secrets restore drill ok from $(basename "$SNAP")"
echo "$LOG_PREFIX To restore for real (tower rebuild):"
echo "  cp $SNAP/secrets/soveryn_vnext.env ~/soveryn_vnext/.env && chmod 600 ~/soveryn_vnext/.env"
echo "  mkdir -p ~/soveryn_vnext/data/canva && cp $SNAP/secrets/canva_tokens.json ~/soveryn_vnext/data/canva/tokens.json && chmod 600 ~/soveryn_vnext/data/canva/tokens.json"
echo "  mkdir -p ~/soveryn_vnext/data/memory/personas && cp $SNAP/secrets/eve_persona.md ~/soveryn_vnext/data/memory/personas/eve.md"
echo "  cp $SNAP/secrets/teammates.env ~/teammates/.env && chmod 600 ~/teammates/.env"
