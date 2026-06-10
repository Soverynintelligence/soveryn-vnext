#!/bin/bash
# scripts/path_migration.sh
#
# Atomic path consolidation: stop services, move data, restart services.
# Run during maintenance window. Reversible (data is moved, not transformed).
#
# Before running:
#   1. Confirm Tasks 1-5 commits have landed (loader/daemons/startup/setup script)
#   2. Run scripts/setup_data_root.sh (idempotent — safe even if already done)
#   3. Optional: snapshot a backup
#      tar czf ~/soveryn_complete_memory_backup_$(date +%Y%m%d-%H%M%S).tar.gz \
#          -C ~/soveryn_complete soveryn_memory
#
# Rollback procedure: see docs/PATH_CONSOLIDATION_RUNBOOK.md

set -eu

OLD_MEMORY="$HOME/soveryn_complete/soveryn_memory"
NEW_MEMORY="$HOME/soveryn_vnext/data/memory"
OLD_TEMPLATES="$HOME/soveryn_complete/templates"
NEW_TEMPLATES="$HOME/soveryn_vnext/data/templates_legacy"
OLD_ROUTER_PRESET="$HOME/soveryn_complete/router-presets.ini"
NEW_ROUTER_PRESET="$HOME/soveryn_vnext/data/router-presets.ini"

echo "=== SOVERYN Path Consolidation Maintenance Window ==="
echo "OLD memory: $OLD_MEMORY"
echo "NEW memory: $NEW_MEMORY"
echo

# Pre-flight: confirm new structure exists
if [ ! -d "$NEW_MEMORY" ]; then
    echo "ERROR: $NEW_MEMORY does not exist. Run scripts/setup_data_root.sh first."
    exit 1
fi

# Step 1: Stop services that hold the DBs open
echo "[1/5] Stopping services that hold DBs..."
systemctl --user stop \
    soveryn-heartbeat.service \
    soveryn-dream.service \
    soveryn-signal-bridge.service \
    soveryn-vett-patrol.service \
    soveryn-vnext.service \
    || true  # tolerant if some are already stopped

sleep 2  # let SQLite WAL flush

# Step 2: Move memory DB files (WAL + SHM siblings via glob)
echo "[2/5] Moving memory database files..."
for prefix in lattice_vnext conversations_vnext salience_vnext; do
    for suffix in "" "-wal" "-shm"; do
        src="$OLD_MEMORY/${prefix}.db${suffix}"
        if [ -e "$src" ]; then
            echo "  mv $src → $NEW_MEMORY/"
            mv "$src" "$NEW_MEMORY/"
        fi
    done
done

# Souls directory
if [ -d "$OLD_MEMORY/souls" ] && [ ! -d "$NEW_MEMORY/souls/.migrated" ]; then
    echo "[3/5] Moving souls directory..."
    # If new souls dir exists from setup script and is empty (just .gitkeep), remove it first
    if [ -d "$NEW_MEMORY/souls" ] && [ -z "$(ls -A "$NEW_MEMORY/souls" 2>/dev/null | grep -v '.gitkeep' | head -1)" ]; then
        rm -rf "$NEW_MEMORY/souls"
    fi
    mv "$OLD_MEMORY/souls" "$NEW_MEMORY/"
    touch "$NEW_MEMORY/souls/.migrated"
fi

# Pinned memory
if [ -f "$OLD_MEMORY/pinned_memory.md" ]; then
    echo "[4/5] Moving pinned memory..."
    echo "  mv $OLD_MEMORY/pinned_memory.md → $NEW_MEMORY/"
    mv "$OLD_MEMORY/pinned_memory.md" "$NEW_MEMORY/"
fi

# Templates — copy, not move (router preset still references old path)
if [ -d "$OLD_TEMPLATES" ] && [ ! -e "$NEW_TEMPLATES/.migrated" ]; then
    echo "  Copying legacy templates..."
    cp -r "$OLD_TEMPLATES"/* "$NEW_TEMPLATES/" 2>/dev/null || true
    touch "$NEW_TEMPLATES/.migrated"
fi

# Router preset — copy only (router systemd unit still references old path)
if [ -f "$OLD_ROUTER_PRESET" ] && [ ! -f "$NEW_ROUTER_PRESET" ]; then
    echo "  Copying router preset (kept in old location until router unit updated)..."
    cp "$OLD_ROUTER_PRESET" "$NEW_ROUTER_PRESET"
fi

# Step 5: Restart services in order
echo "[5/5] Starting services..."
systemctl --user start soveryn-vnext.service
sleep 5  # let vnext warm before downstream daemons spin up

systemctl --user start \
    soveryn-heartbeat.service \
    soveryn-dream.service \
    soveryn-signal-bridge.service \
    soveryn-vett-patrol.service
sleep 3

# Post-migration verification
echo
echo "=== Post-migration service state ==="
for s in soveryn-router soveryn-vnext soveryn-heartbeat soveryn-dream soveryn-signal-bridge soveryn-vett-patrol; do
    state=$(systemctl --user is-active "$s.service" 2>/dev/null)
    printf "  %-30s %s\n" "$s" "$state"
done

echo
echo "=== Quick probes ==="
echo -n "  /api/models: "
curl -s --max-time 10 http://127.0.0.1:5001/api/models 2>&1 | head -c 80
echo
echo -n "  conversations row count: "
sqlite3 "$NEW_MEMORY/conversations_vnext.db" "SELECT COUNT(*) FROM conversations;" 2>&1

echo
echo "=== Migration complete ==="
echo
echo "Next: open the UI, chat with Aetheria, confirm she responds with prior history."
echo "Rollback procedure: docs/PATH_CONSOLIDATION_RUNBOOK.md"
