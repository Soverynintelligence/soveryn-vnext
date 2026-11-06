#!/usr/bin/env bash
# Rollback revamp phases 2-3 on the LIVE pages (message_thread.html, command_center.html,
# Desk context field in api_kernel_desk.py + kernel_desk/manager.py). No sudo.
# Restores the pre-edit copies from backups/revamp-live-pages-20261105/ (taken 2026-11-05 08:52 ET),
# parks the new test file there, then restarts soveryn-vnext only (never the Kernel).
# Note: the plan doc is NOT rolled back (status notes stay); restore it by hand from the same dir if wanted.
set -euo pipefail
R="$HOME/soveryn_vnext"
B="$R/backups/revamp-live-pages-20261105"
cp -a "$B/message_thread.html" "$R/soveryn/app/templates/message_thread.html"
cp -a "$B/command_center.html" "$R/soveryn/app/templates/command_center.html"
cp -a "$B/api_kernel_desk.py"  "$R/soveryn/app/routes/api_kernel_desk.py"
cp -a "$B/manager.py"          "$R/soveryn/kernel_desk/manager.py"
[[ -e "$R/tests/test_live_pages_revamp_ui.py" ]] && mv "$R/tests/test_live_pages_revamp_ui.py" "$B/" || true
systemctl --user restart soveryn-vnext && echo "restored live pages (pre phase 2-3 port); soveryn-vnext restarted $(date)"
