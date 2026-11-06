#!/usr/bin/env bash
# Rollback revamp phase 3 (context meter in chat.html) -> post-phase-2 state. No sudo.
set -euo pipefail
R="$HOME/soveryn_vnext"
cp -a "$R/backups/revamp-phase3-20261105/chat.html" "$R/soveryn/app/templates/chat.html"
[[ -e "$R/tests/test_chat_context_meter_ui.py" ]] && mv "$R/tests/test_chat_context_meter_ui.py" "$R/backups/revamp-phase3-20261105/"
systemctl --user restart soveryn-vnext && echo "restored chat.html (pre-phase3); soveryn-vnext restarted $(date)"
