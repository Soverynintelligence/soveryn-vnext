#!/usr/bin/env bash
# Switch Vett/Scotty (and anything else on Spark :8001) between brains.
#
# Usage:
#   switch_vett_brain.sh              # show current
#   switch_vett_brain.sh qwen36       # Qwen3.6-35B-A3B MoE + MTP (default / daily)
#   switch_vett_brain.sh qwen38       # Qwen3.8-27B dense NVFP4
#   switch_vett_brain.sh lightning    # Nemotron 3.5 Lightning 30B-A3B
#
# What it does:
#   1. Writes ~/.vett-brain on Spark + ~/.soveryn/vett_brain on tower
#   2. Restarts qwen-serve.service on Spark (loads the matching serve-*.sh)
#   3. Restarts soveryn-vnext so runtime.py re-imports the model_alias
#
# Only ONE model fits on the single Spark at a time.
set -euo pipefail

SPARK_HOST="${SPARK_HOST:-spark}"
BRAIN_FILE_TOWER="${HOME}/.soveryn/vett_brain"
VALID='qwen36|qwen38|lightning'

usage() {
  echo "Usage: $0 [qwen36|qwen38|lightning]"
  echo "  qwen36     Qwen3.6-35B-A3B NVFP4 + MTP     (alias qwen36-35b)"
  echo "  qwen38     Qwen3.8-27B dense NVFP4           (alias qwen38-27b)"
  echo "  lightning  Nemotron 3.5 Lightning 30B-A3B    (alias lightning-30b)"
  exit 1
}

current() {
  local t s
  t="$(cat "$BRAIN_FILE_TOWER" 2>/dev/null || echo '?')"
  s="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$SPARK_HOST" 'cat ~/.vett-brain 2>/dev/null || echo ?')"
  echo "tower brain file:  $t"
  echo "spark brain file:  $s"
  echo -n "spark /v1/models: "
  curl -sS -m 5 http://10.10.10.2:8001/v1/models 2>/dev/null \
    | python -c 'import sys,json; d=json.load(sys.stdin); print(",".join(m["id"] for m in d.get("data",[])))' \
    2>/dev/null || echo "(unreachable)"
  echo -n "vnext routing:    "
  cd "$HOME/soveryn_vnext" && /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -c '
from soveryn.config.runtime import resolve_vett_brain, MODEL_SERVERS
key = resolve_vett_brain()
srv = next(s for s in MODEL_SERVERS if s.name == "vett_scotty_shared")
print(f"{key} → alias={srv.model_alias}  {srv.base_url}")
' 2>/dev/null || echo "(import failed)"
}

if [[ $# -eq 0 ]]; then
  current
  exit 0
fi

BRAIN="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
case "$BRAIN" in
  qwen36|qwen38|lightning) ;;
  *) usage ;;
esac

mkdir -p "${HOME}/.soveryn"
echo "$BRAIN" > "$BRAIN_FILE_TOWER"
echo "wrote tower $BRAIN_FILE_TOWER → $BRAIN"

echo "updating Spark ~/.vett-brain and restarting qwen-serve…"
ssh -o BatchMode=yes -o ConnectTimeout=15 "$SPARK_HOST" bash -s <<REMOTE
set -euo pipefail
echo '$BRAIN' > "\$HOME/.vett-brain"
systemctl --user daemon-reload
systemctl --user restart qwen-serve.service
echo "qwen-serve: \$(systemctl --user is-active qwen-serve.service)"
REMOTE

echo "restarting soveryn-vnext so Vett picks up the new model_alias…"
systemctl --user restart soveryn-vnext.service
sleep 2
systemctl --user is-active soveryn-vnext.service

echo
echo "Waiting for Spark :8001 to serve the new model (load can take several minutes)…"
ALIAS=""
case "$BRAIN" in
  qwen36) ALIAS=qwen36-35b ;;
  qwen38) ALIAS=qwen38-27b ;;
  lightning) ALIAS=lightning-30b ;;
esac

for i in $(seq 1 90); do
  body="$(curl -sS -m 3 http://10.10.10.2:8001/v1/models 2>/dev/null || true)"
  if echo "$body" | grep -q "\"$ALIAS\""; then
    echo "ready: $ALIAS (after ~$((i*5))s)"
    current
    echo
    echo "Chat with Vett — she is now on $BRAIN ($ALIAS)."
    exit 0
  fi
  # still loading if connection refused or empty list
  if (( i % 6 == 0 )); then
    echo "  …still loading ($((i*5))s) brain=$BRAIN"
  fi
  sleep 5
done

echo "TIMEOUT: $ALIAS not visible after ~7.5 min. Check: ssh spark 'journalctl --user -u qwen-serve -n 80 --no-pager'"
exit 1
