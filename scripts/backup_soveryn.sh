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
# Cron: 0 4 * * *  scripts/backup_soveryn.sh >> logs/backup.log 2>&1 \
#                    || scripts/alert_signal.sh "Backup failed"
# NOTE: the log used to go to /tmp, which is wiped on every reboot — so there
# was never any history in which to notice a degraded backup. Keep it on disk.
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

# ── Secrets / operator state (NOT in git; must survive tower death) ───────
# Critic 2026-08-24: .env was never in the nightly set — Canva OAuth would
# die with the tower even though tokens.json was copied. Bundle mode 600.
SECRETS="$DEST/secrets"
mkdir -p "$SECRETS"
copy_secret() {
    local src="$1" name="$2"
    if [ -f "$src" ]; then
        cp -p "$src" "$SECRETS/$name"
        chmod 600 "$SECRETS/$name"
        echo "$LOG_PREFIX ✓ secrets/$name"
    else
        echo "$LOG_PREFIX ⚠ secrets/$name missing at $src (skip)"
    fi
}
copy_secret "$BASE/.env" "soveryn_vnext.env"
copy_secret "$DATA/canva/tokens.json" "canva_tokens.json"
copy_secret "$DATA/memory/personas/eve.md" "eve_persona.md"
# Teammates is a sibling repo — same operator, same restore story.
copy_secret "$HOME/teammates/.env" "teammates.env"
copy_secret "$HOME/teammates/roster.toml" "teammates_roster.toml"
# Manifest (no secret values) so a restore drill can assert completeness.
{
    echo "backed_up_at=$(date -Iseconds)"
    echo "host=$(hostname)"
    for f in "$SECRETS"/*; do
        [ -f "$f" ] || continue
        echo "$(basename "$f") sha256=$(sha256sum "$f" | awk '{print $1}') bytes=$(stat -c%s "$f")"
    done
} > "$SECRETS/MANIFEST.txt"
chmod 600 "$SECRETS/MANIFEST.txt"
echo "$LOG_PREFIX ✓ secrets/MANIFEST.txt"

# ── Off-disk mirror to easystore ─────────────────────────────────────────

# A missing mirror used to be SILENT: both the skip and the failure branch
# only echoed, so the script still exited 0 and cron's `|| alert` never fired.
# Local-only backups then looked identical to healthy ones — which is how the
# easystore went unplugged from the Spark install (2026-07) until 07-22 with
# nothing ever saying so. Every non-success path now alerts, and we stamp the
# last good mirror so the alert can say how stale the off-box copy actually is.
MIRROR_STAMP="$BASE/backups/.last_easystore_mirror"
mirror_age_note() {
    if [ -f "$MIRROR_STAMP" ]; then
        local days=$(( ( $(date +%s) - $(stat -c%Y "$MIRROR_STAMP") ) / 86400 ))
        echo "last good off-box mirror ${days}d ago"
    else
        echo "NO off-box mirror has ever succeeded"
    fi
}

if mountpoint -q /mnt/easystore 2>/dev/null && [ -w /mnt/easystore ]; then
    mkdir -p /mnt/easystore/soveryn_backups
    # NO --delete, deliberately (changed 2026-07-22). Local is a ROTATING
    # WORKING SET (7 daily + monthlies, pruned below); the easystore is the
    # PERMANENT ARCHIVE and must keep everything. With --delete the off-box
    # copy could only ever hold what local held, so it protected against the
    # tower dying but NOT against deleting something and noticing weeks later
    # — and the off-box copy is the one that matters. Divergence is intended:
    # easystore will accumulate snapshots that local has already rotated away.
    if rsync -a "$BASE/backups/" /mnt/easystore/soveryn_backups/; then
        touch "$MIRROR_STAMP"
        arch_n=$(find /mnt/easystore/soveryn_backups -maxdepth 1 -type d -name "20*-*-*" | wc -l)
        arch_sz=$(du -sh /mnt/easystore/soveryn_backups 2>/dev/null | cut -f1)
        free_gb=$(df -BG --output=avail /mnt/easystore | tail -1 | tr -dc '0-9')
        echo "$LOG_PREFIX ✓ archived to easystore ($arch_n snapshots, $arch_sz, ${free_gb}G free)"
        # Proactive low-space warning — don't wait for a full disk to fail the sync.
        if [ "${free_gb:-9999}" -lt 500 ]; then
            "$BASE/scripts/alert_signal.sh" \
                "easystore archive low on space: ${free_gb}G free, $arch_n snapshots ($arch_sz). Prune or add a drive." || true
        fi
    else
        echo "$LOG_PREFIX ✗ easystore mirror FAILED — local backup ok, no off-box copy" >&2
        "$BASE/scripts/alert_signal.sh" \
            "Backup DEGRADED — easystore mirror failed ($(mirror_age_note)). Local backup is fine." || true
    fi
else
    echo "$LOG_PREFIX ✗ easystore not mounted read-write — backups are LOCAL-ONLY" >&2
    "$BASE/scripts/alert_signal.sh" \
        "Backup DEGRADED — easystore not mounted rw ($(mirror_age_note)). Backups are LOCAL-ONLY, same box as the data." || true
fi

# ── Rotation: keep 7 daily; keep 1st-of-month for ~3 months ──────────────
find "$BASE/backups" -maxdepth 1 -type d -name "20*-*-*" -mtime +7 \
    ! -name "20*-*-01" -exec rm -rf {} + 2>/dev/null || true
find "$BASE/backups" -maxdepth 1 -type d -name "20*-*-01" -mtime +95 \
    -exec rm -rf {} + 2>/dev/null || true

total_size=$(du -sh "$DEST" | cut -f1)
backup_count=$(find "$BASE/backups" -maxdepth 1 -type d -name "20*-*-*" | wc -l)
echo "$LOG_PREFIX ✓ DONE — $db_count DBs, today's backup $total_size, $backup_count retained locally"
