#!/usr/bin/env bash
# Restore lattice_vnext.db from pre-prune backup (conclusion dedupe prune, 20261105-225847).
set -euo pipefail
cd "$(dirname "$0")/../.."
BK="${1:-backups/lattice-conclusion-prune-20261105-225847/lattice_vnext.db}"
DB=data/memory/lattice_vnext.db
systemctl --user stop soveryn-representation.service || true
sqlite3 "$DB" ".restore '$BK'"
sqlite3 "$DB" "SELECT 'conclusions after rollback', COUNT(*) FROM nodes WHERE type='conclusion';"
systemctl --user start soveryn-representation.service || true
