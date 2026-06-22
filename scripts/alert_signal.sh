#!/usr/bin/env bash
# SOVERYN Signal alert helper — rewritten 2026-06-22 for the archive migration.
# Calls signal-cli DIRECTLY (no Python, no soveryn_complete.tools.signal_gateway
# import — that import was a cord into the old tree). Bot/user numbers + cli
# path come from ~/soveryn_vnext/.env, with the known-good values as fallback.
#
# Usage: scripts/alert_signal.sh "message"
set -uo pipefail

MSG="${1:-No message provided}"
BASE="$(cd "$(dirname "$0")/.." && pwd)"   # → ~/soveryn_vnext

# Load .env if present (cron has no profile). Tolerate its absence.
if [ -f "$BASE/.env" ]; then
    set -a; # shellcheck disable=SC1091
    . "$BASE/.env" 2>/dev/null || true
    set +a
fi

BOT="${SIGNAL_BOT_NUMBER:-+19102489392}"
USER_NUM="${SIGNAL_USER_NUMBER:-+19105813970}"
CLI="${SIGNAL_CLI_BIN:-/usr/local/bin/signal-cli}"

if [ ! -x "$CLI" ] && ! command -v "$CLI" >/dev/null 2>&1; then
    echo "[alert] signal-cli not found at '$CLI' — cannot send: $MSG" >&2
    exit 1
fi

"$CLI" -a "$BOT" send -m "[SOVERYN ALERT] $MSG" "$USER_NUM"
