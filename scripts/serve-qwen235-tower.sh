#!/usr/bin/env bash
# Qwen3-235B-A22B Q4_K_M on the tower — large MoE test lane.
#
# Uses the two Quadros (NVLink pair) + system RAM. Leaves Blackwell for Aetheria.
# Device order in the cuda131 build: CUDA0=Blackwell, CUDA1/2=Quadros.
#
# MoE experts stay on CPU/RAM (~133 GB weights; 512 GB host has headroom).
# Non-expert layers fit on the two 48 GB Quadros.
#
# Usage:
#   ~/soveryn_vnext/scripts/serve-qwen235-tower.sh          # foreground
#   ~/soveryn_vnext/scripts/serve-qwen235-tower.sh --bg     # background log
#
# Smoke:
#   curl -s http://127.0.0.1:8100/v1/models
#   curl -s http://127.0.0.1:8100/v1/chat/completions -H 'Content-Type: application/json' \
#     -d '{"model":"qwen235-a22b","messages":[{"role":"user","content":"Say READY in one word."}],"max_tokens":16,"temperature":0}'
set -euo pipefail

export LD_LIBRARY_PATH="/home/jon-deoliveira/miniconda3/envs/cuda131/cuda-compat:/home/jon-deoliveira/miniconda3/envs/cuda131/lib:${LD_LIBRARY_PATH:-}"

BIN="${LLAMA_SERVER_BIN:-/home/jon-deoliveira/llama.cpp_head/build-cuda131/bin/llama-server}"
MODEL="${QWEN235_MODEL:-/mnt/soveryn_models/GGUF/qwen3-235b-a22b-q4km/Qwen3-235B-A22B-Q4_K_M-00001-of-00003.gguf}"
HOST="${QWEN235_HOST:-127.0.0.1}"
PORT="${QWEN235_PORT:-8100}"
# CUDA1,CUDA2 = two Quadros in this build's enumeration (not Blackwell)
DEVICES="${QWEN235_DEVICES:-CUDA1,CUDA2}"
CTX="${QWEN235_CTX:-16384}"
THREADS="${QWEN235_THREADS:-32}"
LOG="${QWEN235_LOG:-/tmp/qwen235-tower.log}"

if [[ ! -x "$BIN" ]]; then
  echo "missing llama-server: $BIN" >&2
  exit 1
fi
if [[ ! -e "$MODEL" ]]; then
  echo "missing model: $MODEL" >&2
  exit 1
fi

# Free ~25–30 GB per Quadro is enough for non-expert layers; experts → CPU.
# Pattern matches Qwen3 MoE expert tensors (llama.cpp / community recipe).
ARGS=(
  --model "$MODEL"
  --alias qwen235-a22b
  --host "$HOST"
  --port "$PORT"
  --ctx-size "$CTX"
  --parallel 1
  --jinja
  --flash-attn on
  --cache-type-k q8_0
  --cache-type-v q8_0
  --device "$DEVICES"
  --split-mode layer
  --tensor-split 50,50
  --n-gpu-layers 99
  --override-tensor "exps=CPU"
  --threads "$THREADS"
  --fit on
  --fit-target 2048
)

echo "Qwen3-235B-A22B → ${HOST}:${PORT} devices=${DEVICES} ctx=${CTX}"
echo "log: $LOG"
echo "model: $MODEL"

if [[ "${1:-}" == "--bg" ]]; then
  # shellcheck disable=SC2024
  nohup "$BIN" "${ARGS[@]}" >"$LOG" 2>&1 &
  echo $! > /tmp/qwen235-tower.pid
  echo "pid $(cat /tmp/qwen235-tower.pid) — tail -f $LOG"
  exit 0
fi

exec "$BIN" "${ARGS[@]}"
