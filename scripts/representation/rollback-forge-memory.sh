#!/usr/bin/env bash
set -euo pipefail
BACKUP="/home/jon-deoliveira/soveryn_vnext/backups/forge-memory-20261106-205603"
if [[ "${1:-}" == "--restore-db" ]]; then
 echo "Refusing blind shared-lattice restoration; obtain Jon's recovery approval." >&2
 exit 2
fi
systemctl --user stop soveryn-representation.service
RESTORE_APP=$(python - "$BACKUP" <<'CHECK'
import json,sys,sqlite3
from pathlib import Path
b=Path(sys.argv[1]);m=json.loads((b/'manifest.json').read_text());r=Path(m['root'])
c=sqlite3.connect(f"file:{r}/data/memory/lattice_vnext.db?mode=ro",uri=True)
n=c.execute("SELECT count(*) FROM nodes WHERE agent='forge' AND layer='private'").fetchone()[0]
print("no" if n else "yes")
CHECK
)
if [[ "$RESTORE_APP" == "yes" ]]; then
 systemctl --user stop soveryn-vnext.service
else
 echo "Keeping lookup privacy guard and its tests: private Forge nodes now exist. App stays running." >&2
fi
python - "$BACKUP" "$RESTORE_APP" <<'RESTORE'
import json,sys,shutil
from pathlib import Path
b=Path(sys.argv[1]);m=json.loads((b/'manifest.json').read_text());r=Path(m['root']);restore_app=sys.argv[2]=="yes"
for f in m['files']:
 if f in m.get('app_files',[]) and not restore_app:continue
 shutil.copy2(b/f,r/f)
for f in m['new']:(r/f).unlink(missing_ok=True)
for name in m['restore_units']:shutil.copy2(b/name,m['units'][name])
RESTORE
systemctl --user daemon-reload
if [[ "$RESTORE_APP" == "yes" ]]; then systemctl --user start soveryn-vnext.service; fi
systemctl --user start soveryn-representation.service
echo "Pre-Forge representation restored; shared lattice never overwritten. $BACKUP"
