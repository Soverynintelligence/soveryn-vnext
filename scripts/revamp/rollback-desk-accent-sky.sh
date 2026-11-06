#!/usr/bin/env bash
set -euo pipefail
R="$HOME/soveryn_vnext"; B="$R/backups/desk-accent-sky-20261105"
[[ -f "$B/desk.css" ]] && cp -a "$B/desk.css" "$R/soveryn/static/desk.css"
[[ -f "$B/ui.py" ]] && cp -a "$B/ui.py" "$R/soveryn/app/routes/ui.py"
for f in "$B"/*.html; do
  bn=$(basename "$f")
  [[ -f "$R/soveryn/app/templates/$bn" ]] && cp -a "$f" "$R/soveryn/app/templates/$bn"
done
[[ -f "$B/_messages_sidebar.html" ]] && cp -a "$B/_messages_sidebar.html" "$R/soveryn/app/templates/_messages_sidebar.html"
systemctl --user restart soveryn-vnext
echo "restored pre-sky accent; restarted $(date)"
