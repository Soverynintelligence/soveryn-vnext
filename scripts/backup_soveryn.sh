#!/usr/bin/env bash
# SOVERYN vNext nightly backup — rewritten 2026-06-22 during the
# soveryn_complete archive migration.
#
# The previous backup (in soveryn_complete/scripts) targeted
# soveryn_complete/soveryn_memory/*.db — the OLD system's now-stale DBs —
# while the live vNext memory in ~/soveryn_vnext/data went un-backed-up.
# This version backs up the live vNext data root.
#
# Design choice: DBs are DISCOVERED dynamically under data/ (find), not
# hardcoded — a hardcoded name list is exactly what silently went stale
# before. Uses sqlite3 .backup (online API, WAL-safe) + integrity check.
# Mirrors to /mnt/easystore if mounted; rotates old daily backups.
#
# Cron: 0 4 * * *  scripts/backup_soveryn.sh >> /tmp/soveryn_backup.log 2>&1 \
#                    || scripts/alert_signal.sh "Backup failed"
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"   # → ~/soveryn_vnext
DATA="$BASE/data"
DATE=$(date +%Y-%m-%d)
DEST="$BASE/backups/$DATE"
LOG_PREFIX="[backup $(date +%H:%M:%S)]"

mkdir -p "$DEST"
echo "$LOG_PREFIX starting backup of $DATA → $DEST"

# ── SQLite DBs (discovered, online backup API, WAL-safe) ─────────────────
db_count=0
while IFS= read -r src; do
    rel="${src#$DATA/}"                       # preserve subdir structure
    dst="$DEST/data/$rel"
    mkdir -p "$(dirname "$dst")"

    sqlite3 "$src" ".backup '$dst'"

    result=$(sqlite3 "$dst" "PRAGMA integrity_check;")
    if [ "$result" != "ok" ]; then
        echo "$LOG_PREFIX ✗ INTEGRITY FAIL on $rel: $result" >&2
        "$BASE/scripts/alert_signal.sh" "Backup integrity FAIL: $rel ($result)" || true
        exit 1
    fi
    src_size=$(stat -c%s "$src")
    dst_size=$(stat -c%s "$dst")
    echo "$LOG_PREFIX ✓ $rel ($src_size → $dst_size bytes, integrity ok)"
    db_count=$((db_count + 1))
done < <(find "$DATA" -type f -name '*.db' ! -name '*-wal' ! -name '*-shm' ! -name '*-journal' | sort)

if [ "$db_count" -eq 0 ]; then
    echo "$LOG_PREFIX ✗ no .db files found under $DATA — refusing to call this a backup" >&2
    "$BASE/scripts/alert_signal.sh" "Backup found ZERO databases under $DATA — misconfigured?" || true
    exit 1
fi

# ── Souls + pinned memory + small state files (atomic cp) ────────────────
[ -d "$DATA/memory/souls" ] && cp -rp "$DATA/memory/souls" "$DEST/data/souls" \
    && echo "$LOG_PREFIX ✓ souls/"
while IFS= read -r f; do
    rel="${f#$DATA/}"
    dst="$DEST/data/$rel"
    mkdir -p "$(dirname "$dst")"
    cp -p "$f" "$dst" && echo "$LOG_PREFIX ✓ $rel"
done < <(find "$DATA" -maxdepth 3 -type f \( -name '*.md' -o -name '*.json' \) 2>/dev/null | sort)

# ── Off-disk mirror to easystore if mounted ──────────────────────────────
if mountpoint -q /mnt/easystore 2>/dev/null && [ -w /mnt/easystore ]; then
    mkdir -p /mnt/easystore/soveryn_backups
    rsync -a --delete "$BASE/backups/" /mnt/easystore/soveryn_backups/ \
        && echo "$LOG_PREFIX ✓ mirrored to easystore" \
        || echo "$LOG_PREFIX ⚠ easystore mirror failed (local backup ok)"
else
    echo "$LOG_PREFIX ⚠ easystore not mounted, skipping mirror"
fi

# ── Rotation: keep 7 daily; keep 1st-of-month for ~3 months ──────────────
find "$BASE/backups" -maxdepth 1 -type d -name "20*-*-*" -mtime +7 \
    ! -name "20*-*-01" -exec rm -rf {} + 2>/dev/null || true
find "$BASE/backups" -maxdepth 1 -type d -name "20*-*-01" -mtime +95 \
    -exec rm -rf {} + 2>/dev/null || true

total_size=$(du -sh "$DEST" | cut -f1)
backup_count=$(find "$BASE/backups" -maxdepth 1 -type d -name "20*-*-*" | wc -l)
echo "$LOG_PREFIX ✓ DONE — $db_count DBs, today's backup $total_size, $backup_count retained locally"
