#!/usr/bin/env bash
set -euo pipefail
BACKUP="/home/jon-deoliveira/soveryn_vnext/backups/representation-fix-20261106-202545"
# Default restores ONLY code/unit; never deletes historical or new lattice nodes.
# --restore-db overwrites ALL lattice changes since backup; obtain Jon's approval first.
if [[ "${1:-}" == "--restore-db" ]]; then
  echo "DB restore requires a separately reviewed recovery plan: shared live lattice may have other writers." >&2
  exit 2
fi
systemctl --user stop soveryn-representation.service
python - "$BACKUP" <<'RESTORE'
import json,sys,shutil
from pathlib import Path
b=Path(sys.argv[1]);m=json.loads((b/'manifest.json').read_text());r=Path(m['root'])
for name in m['existing']: shutil.copy2(b/name,r/name)
for name in m['new']: (r/name).unlink(missing_ok=True)
shutil.copy2(b/'soveryn-representation.service',m['unit'])
RESTORE
systemctl --user daemon-reload
systemctl --user start soveryn-representation.service
echo "Representation code/unit restored; lattice left intact. Backup: $BACKUP"
