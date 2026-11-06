#!/usr/bin/env bash
# Rollback revamp phase 1 (desk danger gate + CLI lease check). No sudo.
set -euo pipefail
R="$HOME/soveryn_vnext"; B="$R/backups/revamp-phase1-20261105"
for f in soveryn/kernel_desk/manager.py packages/soveryn-cli/src/presets.js packages/soveryn-cli/src/cli.js soveryn/app/startup.py; do
  cp -a "$B/$f" "$R/$f"; echo "restored $f"
done
# New files are moved aside (not deleted)
mkdir -p "$B/removed"
for f in soveryn/kernel_desk/danger.py soveryn/kernel_desk/gate.py soveryn/app/routes/api_desk_gate.py \
         soveryn/app/templates/desk_gate.html packages/soveryn-cli/extensions/danger-gate.ts \
         tests/test_desk_danger.py tests/test_api_desk_gate.py packages/soveryn-cli/src/lease-check.js packages/soveryn-cli/test/lease-check.test.cjs packages/soveryn-cli/extensions/danger-gate.ts packages/soveryn-cli/test/danger-gate.test.cjs; do
  [[ -e "$R/$f" ]] && mv "$R/$f" "$B/removed/$(basename $f)" && echo "moved aside $f"
done
systemctl --user restart soveryn-vnext && echo "soveryn-vnext restarted $(date)"
