#!/usr/bin/env bash
# SOVERYN vNext restore drill — rewritten 2026-06-22 for the vNext data root.
# An untested backup is hope, not a backup. Drills the latest backup's
# lattice_vnext.db — the critical memory graph (tables: nodes, edges).
#
# Cron: 0 5 * * 0  scripts/restore_drill.sh >> /tmp/soveryn_drill.log 2>&1 \
#                    || scripts/alert_signal.sh "Restore drill FAILED"
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"   # → ~/soveryn_vnext
LIVE_LATTICE="$BASE/data/memory/lattice_vnext.db"
LOG_PREFIX="[drill $(date +%Y-%m-%d_%H:%M:%S)]"

LATEST=$(ls -td "$BASE"/backups/20*-*-* 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    echo "$LOG_PREFIX ✗ FAIL: no backup directories found in $BASE/backups/"
    exit 1
fi
echo "$LOG_PREFIX starting drill against $LATEST"

LATTICE_BACKUP="$LATEST/data/memory/lattice_vnext.db"
if [ ! -f "$LATTICE_BACKUP" ]; then
    echo "$LOG_PREFIX ✗ FAIL: $LATTICE_BACKUP missing"
    exit 1
fi

TMPDB=$(mktemp --suffix=.db)
trap 'rm -f "$TMPDB" "$TMPDB-wal" "$TMPDB-shm"' EXIT
cp "$LATTICE_BACKUP" "$TMPDB"

# 1. Integrity
INTEG=$(sqlite3 "$TMPDB" "PRAGMA integrity_check;")
if [ "$INTEG" != "ok" ]; then
    echo "$LOG_PREFIX ✗ FAIL: integrity_check returned: $INTEG"; exit 1
fi
echo "$LOG_PREFIX ✓ integrity check passed"

# 2. Schema present
TABLES=$(sqlite3 "$TMPDB" ".tables")
for required in nodes edges; do
    case "$TABLES" in
        *"$required"*) ;;
        *) echo "$LOG_PREFIX ✗ FAIL: required table '$required' missing"; exit 1 ;;
    esac
done
echo "$LOG_PREFIX ✓ schema check passed (tables: $TABLES)"

# 3. Sanity counts (generic — no column assumptions)
NODE_COUNT=$(sqlite3 "$TMPDB" "SELECT COUNT(*) FROM nodes;")
EDGE_COUNT=$(sqlite3 "$TMPDB" "SELECT COUNT(*) FROM edges;")
echo "$LOG_PREFIX restore stats: nodes=$NODE_COUNT edges=$EDGE_COUNT"
if [ "$NODE_COUNT" -lt 500 ]; then
    echo "$LOG_PREFIX ✗ FAIL: node count $NODE_COUNT < 500 (threshold)"; exit 1
fi

# 4. Drift vs live (warn-only)
LIVE_NODES=$(sqlite3 "$LIVE_LATTICE" "SELECT COUNT(*) FROM nodes;" 2>/dev/null || echo 0)
if [ "$LIVE_NODES" -gt 0 ]; then
    DIFF=$((LIVE_NODES - NODE_COUNT)); DIFF_ABS=${DIFF#-}
    PCT=$((DIFF_ABS * 100 / (LIVE_NODES + 1)))
    if [ "$PCT" -gt 20 ]; then
        echo "$LOG_PREFIX ⚠ WARN: backup is $PCT% off live ($NODE_COUNT vs $LIVE_NODES) — may be stale."
    else
        echo "$LOG_PREFIX ✓ drift check ok ($PCT% off live)"
    fi
fi

echo "$LOG_PREFIX ✓ DRILL PASSED"
