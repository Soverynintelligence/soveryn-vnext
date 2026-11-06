#!/usr/bin/env bash
# Rollback revamp phase 2 (tool-use chip in chat.html). No sudo.
set -euo pipefail
R="$HOME/soveryn_vnext"
cp -a "$R/backups/revamp-phase2-20261105/chat.html" "$R/soveryn/app/templates/chat.html"
systemctl --user restart soveryn-vnext && echo "restored chat.html (pre-phase2); soveryn-vnext restarted $(date)"
mkdir -p "$R/backups/revamp-phase2-20261105"; [[ -e "$R/tests/test_chat_turn_tools_ui.py" ]] && mv "$R/tests/test_chat_turn_tools_ui.py" "$R/backups/revamp-phase2-20261105/" || true
