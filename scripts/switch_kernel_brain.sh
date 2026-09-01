#!/usr/bin/env bash
# Switch Kernel between GLM (dual Spark), Quadros Qwen3.8, or Spark Qwen3.8 NVFP4.
#
# Usage:
#   switch_kernel_brain.sh                 # show current
#   switch_kernel_brain.sh glm             # GLM-5.3-Flash TP=2 on Sparks :8001 (live)
#   switch_kernel_brain.sh flash           # Qwen3.8 GGUF on Quadros :8091 (legacy)
#   switch_kernel_brain.sh qwen38          # Qwen3.8-27B NVFP4 on Spark :8001
#   switch_kernel_brain.sh qwen38 --take-spark
#
# Eve stays on Quadros Qwen 3.8 either way.
set -euo pipefail

SPARK_HOST="${SPARK_HOST:-spark}"
SPARK_URL="${SPARK_URL:-http://10.10.10.2:8001}"
BRAIN_FILE_TOWER="${HOME}/.soveryn/kernel_brain"
REPO="${HOME}/soveryn_vnext"
PY="${SOVERYN_PYTHON:-/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python}"
VETT_SWITCH="${REPO}/scripts/switch_vett_brain.sh"

usage() {
  echo "Usage: $0 [glm|flash|qwen38] [--take-spark]"
  echo "  glm      GLM-5.3-Flash EXL3 TR3 4bpw TP=2 on Sparks :8001 (alias glm-5.3-flash)"
  echo "  flash    Qwen3.8 GGUF on Quadros :8091 (legacy alias bench-flash)"
  echo "  qwen38   Qwen3.8-27B NVFP4 on Spark :8001 (alias qwen38-27b)"
  echo "  --take-spark   with qwen38: load that brain on Spark via switch_vett_brain.sh"
  exit 1
}

current() {
  local t
  t="$(cat "$BRAIN_FILE_TOWER" 2>/dev/null || echo 'flash (default)')"
  echo "tower kernel brain file:  $t"
  echo -n "spark /v1/models:         "
  curl -sS -m 5 "$SPARK_URL/v1/models" 2>/dev/null \
    | "$PY" -c 'import sys,json; d=json.load(sys.stdin); print(",".join(m["id"] for m in d.get("data",[])))' \
    2>/dev/null || echo "(unreachable)"
  echo -n "quadro kernel aliases:    "
  curl -sS -m 5 http://127.0.0.1:8091/v1/models 2>/dev/null \
    | "$PY" -c 'import sys,json; d=json.load(sys.stdin); print(",".join(m["id"] for m in d.get("data",[])))' \
    2>/dev/null || echo "(unreachable)"
  echo -n "vnext Kernel routing:     "
  cd "$REPO" && "$PY" -c '
from soveryn.config.runtime import resolve_kernel_brain, MODEL_SERVERS, AGENT_TO_SERVER
key = resolve_kernel_brain()
srv = next(s for s in MODEL_SERVERS if s.name == "kernel_build")
eve = next(s for s in MODEL_SERVERS if s.name == AGENT_TO_SERVER["eve"])
print(f"{key} → alias={srv.model_alias}  {srv.base_url}")
print(f"vnext Eve routing:        pinned → alias={eve.model_alias}  {eve.base_url}")
' 2>/dev/null || echo "(import failed)"
}

TAKE_SPARK=0
BRAIN=""
for arg in "$@"; do
  case "$arg" in
    --take-spark) TAKE_SPARK=1 ;;
    -h|--help) usage ;;
    flash|qwen38|glm) BRAIN="$arg" ;;
    *)
      if [[ -n "$arg" ]]; then
        echo "unknown arg: $arg" >&2
        usage
      fi
      ;;
  esac
done

if [[ -z "$BRAIN" ]]; then
  current
  exit 0
fi

mkdir -p "${HOME}/.soveryn"
echo "$BRAIN" > "$BRAIN_FILE_TOWER"
echo "wrote tower $BRAIN_FILE_TOWER → $BRAIN"

if [[ "$BRAIN" == "glm" ]]; then
  body="$(curl -sS -m 5 "$SPARK_URL/v1/models" 2>/dev/null || true)"
  if ! echo "$body" | grep -q '"glm-5.3-flash"'; then
    echo "ERROR: Spark :8001 is not serving glm-5.3-flash." >&2
    echo "  Current Spark models: $(echo "$body" | "$PY" -c 'import sys,json; d=json.load(sys.stdin); print(",".join(m["id"] for m in d.get("data",[])))' 2>/dev/null || echo '?')" >&2
    exit 2
  fi
  echo "Spark already serving glm-5.3-flash"
fi

if [[ "$BRAIN" == "qwen38" ]]; then
  body="$(curl -sS -m 5 "$SPARK_URL/v1/models" 2>/dev/null || true)"
  if ! echo "$body" | grep -q '"qwen38-27b"'; then
    if [[ "$TAKE_SPARK" -eq 1 ]]; then
      echo "Spark is not on qwen38-27b — running switch_vett_brain.sh qwen38 …"
      bash "$VETT_SWITCH" qwen38
    else
      echo "ERROR: Spark :8001 is not serving qwen38-27b." >&2
      echo "  Current Spark models: $(echo "$body" | "$PY" -c 'import sys,json; d=json.load(sys.stdin); print(",".join(m["id"] for m in d.get("data",[])))' 2>/dev/null || echo '?')" >&2
      echo "  Load it first:  $VETT_SWITCH qwen38" >&2
      echo "  Or retarget + load:  $0 qwen38 --take-spark" >&2
      exit 2
    fi
  else
    echo "Spark already serving qwen38-27b"
  fi
fi

echo "restarting soveryn-vnext so Kernel picks up the new route…"
systemctl --user restart soveryn-vnext.service
sleep 2
systemctl --user is-active soveryn-vnext.service
echo
current
