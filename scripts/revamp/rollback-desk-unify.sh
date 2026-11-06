#!/usr/bin/env bash
# Roll back the 2026-11-05 Desk house-style unify (Option A, charcoal + copper).
# Restores every edited template + ui.py from backups/desk-unify-20261105,
# moves the new shared stylesheet aside, restarts soveryn-vnext only.
set -euo pipefail
R="$HOME/soveryn_vnext"
B="$R/backups/desk-unify-20261105"
T="$R/soveryn/app/templates"
for f in "$B"/templates/*.html; do cp -a "$f" "$T/$(basename "$f")"; done
cp -a "$B/routes/ui.py" "$R/soveryn/app/routes/ui.py"
cp -a "$B/routes/api_desk_gate.py" "$R/soveryn/app/routes/api_desk_gate.py"
cp -a "$B/static/softdesk.css" "$R/soveryn/static/softdesk.css"
cp -a "$B/static/lab-console.css" "$R/soveryn/static/lab-console.css"
if [ -f "$R/soveryn/static/desk.css" ]; then
  mv "$R/soveryn/static/desk.css" "$B/desk.css.rolled-back-$(date +%Y%m%d-%H%M%S)"
fi
(cd "$B" && sha256sum -c SHA256SUMS --quiet) || echo "WARN: backup checksum mismatch"
systemctl --user restart soveryn-vnext
echo "desk-unify rolled back; soveryn-vnext restarted $(date)"
