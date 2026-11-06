#!/usr/bin/env bash
set -euo pipefail
R="$HOME/soveryn_vnext"
cp -a "$R/backups/revamp-desk-gate-link-20261105/command_center.html" "$R/soveryn/app/templates/command_center.html"
systemctl --user restart soveryn-vnext
echo "restored command_center.html (pre desk-gate link); soveryn-vnext restarted $(date)"
