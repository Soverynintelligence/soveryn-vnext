#!/bin/bash
# SOVERYN router watchdog.
#
# Built 2026-06-08 after Aetheria's Blackwell child hit a CUDA "launch timed
# out" (display TDR) at 15:39 EDT, ggml_abort()-ed, and the router on :8090
# kept proxying chat requests to its dead port for 3+ hours because the
# router's internal state still said "loaded."
#
# What this does:
#   1. Hits /v1/models on the router; for each model whose status.value=="loaded",
#      probes its endpoint with a 1-token request.
#   2. If any "loaded" model fails to respond, restarts soveryn-router.service.
#   3. Cooldown guard prevents restart loops.
#
# Honest scope: this catches DEAD children whose router state lies about them.
# It does NOT catch a wedged child (responding slowly but not crashed). That's
# a separate, less-common failure mode.

set -u

ROUTER_HOST="${ROUTER_HOST:-127.0.0.1}"
ROUTER_PORT="${ROUTER_PORT:-8090}"
PROBE_TIMEOUT="${PROBE_TIMEOUT:-20}"
MODELS_TIMEOUT="${MODELS_TIMEOUT:-10}"
RESTART_COOLDOWN_SEC="${RESTART_COOLDOWN_SEC:-300}"
COOLDOWN_FILE="/tmp/soveryn-router-watchdog.last-restart"
LOG_TAG="soveryn-router-watchdog"

log() {
    local msg="$1"
    logger -t "$LOG_TAG" "$msg"
    printf '%s %s\n' "$(date -Iseconds)" "$msg"
}

# 1. Router itself responsive?
models_json=$(curl -s --max-time "$MODELS_TIMEOUT" "http://${ROUTER_HOST}:${ROUTER_PORT}/v1/models")
if [ -z "$models_json" ]; then
    log "ERROR: /v1/models returned nothing — router process itself is down or unresponsive; systemd Restart=on-failure should handle this, not us"
    exit 1
fi

# 2. Loaded models + their kind (chat vs embeddings) from the preset string
mapfile -t loaded < <(
    printf '%s' "$models_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
for m in data.get("data", []):
    status = m.get("status", {})
    if status.get("value") != "loaded":
        continue
    alias = m["id"]
    preset = status.get("preset", "")
    kind = "embeddings" if ("embeddings = true" in preset or "embeddings=true" in preset) else "chat"
    print(f"{alias}\t{kind}")
'
)

if [ "${#loaded[@]}" -eq 0 ]; then
    log "INFO: no loaded models — nothing to probe"
    exit 0
fi

# 3. Probe each loaded alias
broken=""
for entry in "${loaded[@]}"; do
    alias="${entry%%$'\t'*}"
    kind="${entry##*$'\t'}"
    if [ "$kind" = "embeddings" ]; then
        path="/v1/embeddings"
        body=$(printf '{"model":"%s","input":"hi"}' "$alias")
    else
        path="/v1/chat/completions"
        body=$(printf '{"model":"%s","messages":[{"role":"user","content":"hi"}],"max_tokens":1,"stream":false}' "$alias")
    fi
    http_code=$(curl -s --max-time "$PROBE_TIMEOUT" -o /dev/null -w '%{http_code}' \
        -X POST "http://${ROUTER_HOST}:${ROUTER_PORT}${path}" \
        -H 'Content-Type: application/json' \
        -d "$body" 2>/dev/null)
    if [ "$http_code" != "200" ]; then
        broken="${broken}${broken:+ }${alias}(http=${http_code:-no_response})"
    fi
done

if [ -z "$broken" ]; then
    log "INFO: all ${#loaded[@]} loaded model(s) responsive"
    exit 0
fi

# 4. Cooldown guard
if [ -f "$COOLDOWN_FILE" ]; then
    last=$(cat "$COOLDOWN_FILE" 2>/dev/null || printf '0')
    elapsed=$(( $(date +%s) - last ))
    if [ "$elapsed" -lt "$RESTART_COOLDOWN_SEC" ]; then
        log "WARN: broken=[${broken}] but in cooldown (${elapsed}s/${RESTART_COOLDOWN_SEC}s since last restart) — skipping"
        exit 0
    fi
fi

# 5. Restart
log "ALERT: broken=[${broken}] — restarting soveryn-router.service"
date +%s > "$COOLDOWN_FILE"
if systemctl --user restart soveryn-router.service; then
    log "INFO: router restart issued OK"
else
    log "ERROR: router restart failed exit=$?"
fi
exit 0
