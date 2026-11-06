#!/usr/bin/env bash
set -euo pipefail
R="$HOME/soveryn_vnext"
B="$R/backups/desk-accent-blue-20261105"
cp -a "$B/." "$R/soveryn/static/" 2>/dev/null || true
# restore known files from backup root
for f in desk.css; do [[ -f "$B/$f" ]] && cp -a "$B/$f" "$R/soveryn/static/$f"; done
[[ -f "$B/ui.py" ]] && cp -a "$B/ui.py" "$R/soveryn/app/routes/ui.py"
for f in "$B"/*.html; do
  bn=$(basename "$f")
  if [[ -f "$R/soveryn/app/templates/$bn" ]]; then cp -a "$f" "$R/soveryn/app/templates/$bn"; fi
done
[[ -f "$B/_messages_sidebar.html" ]] && cp -a "$B/_messages_sidebar.html" "$R/soveryn/app/templates/_messages_sidebar.html"
systemctl --user restart soveryn-vnext
echo "restored pre-blue accent; soveryn-vnext restarted $(date)"
