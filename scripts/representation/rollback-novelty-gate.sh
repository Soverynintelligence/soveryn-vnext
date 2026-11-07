#!/usr/bin/env bash
# Roll back the LIVE representation novelty gate (wired 2026-11-06).
# Restores daemon.py, writeback.py, novelty_gate_check.py, the gate test and
# CURRENT_TRUTH.md from the backup, removes the new module + status file, and
# restarts ONLY soveryn-representation.service. The gate never wrote to the
# lattice, so the DB is NOT restored unless you pass --restore-db.
set -euo pipefail
ROOT=/home/jon-deoliveira/soveryn_vnext
B=${NOVELTY_GATE_BACKUP:-$ROOT/backups/novelty-gate-20261106-201457}
cd "$ROOT"
[ -d "$B" ] || { echo "backup $B missing" >&2; exit 1; }
for f in soveryn/agents/representation/daemon.py soveryn/agents/representation/writeback.py \
         scripts/representation/novelty_gate_check.py tests/test_representation_novelty_gate.py \
         docs/CURRENT_TRUTH.md; do
  cp -p "$B/$f" "$ROOT/$f"; echo "restored $f"
done
rm -f soveryn/agents/representation/novelty_gate.py data/memory/representation_novelty_gate_status.json
if [ "${1:-}" = "--restore-db" ]; then
  systemctl --user stop soveryn-representation.service
  echo "WARNING: other services also write lattice_vnext.db; restoring loses their writes since backup."
  cp -p "$B/lattice_vnext.db" data/memory/lattice_vnext.db
  rm -f data/memory/lattice_vnext.db-wal data/memory/lattice_vnext.db-shm
fi
systemctl --user restart soveryn-representation.service
systemctl --user is-active soveryn-representation.service
