#!/usr/bin/env bash
# soveryn-restart — restart the full SOVERYN service stack in dependency order.
#
# This is the canonical "restart everything" command Jon asked for.
# It explicitly hits each service in the right order rather than relying
# on systemd's PartOf= cascade rules (which can be fragile across unit
# files that may or may not have been re-installed lately).
#
# Order:
#   1. Foundation services (router, searxng, cognition, parakeet, comfyui)
#      — these are the model / inference / media surfaces other agents
#      depend on. Router first because llama-server child processes take
#      ~10-20s to load Aetheria's Q8 weights.
#   2. App layer (vnext) — depends on router being live.
#   3. Background agents (heartbeat, vett-patrol, dream, ares, signal-bridge)
#      — these poll/observe; can come up after vnext.
#
# Usage:
#   ~/soveryn_vnext/scripts/soveryn-restart.sh             # restart all
#   ~/soveryn_vnext/scripts/soveryn-restart.sh status      # just show state
#   ~/soveryn_vnext/scripts/soveryn-restart.sh --no-wait   # don't sleep between tiers

set -euo pipefail

FOUNDATION=(
    soveryn-router
    soveryn-searxng
    soveryn-cognition
    parakeet
    soveryn-comfyui
)

APP=(
    soveryn-vnext
)

BACKGROUND=(
    soveryn-heartbeat
    soveryn-vett-patrol
    soveryn-dream
    soveryn-ares
    soveryn-signal-bridge
)

ALL=("${FOUNDATION[@]}" "${APP[@]}" "${BACKGROUND[@]}")

action="${1:-restart}"
wait_between_tiers=true
for arg in "$@"; do
    if [ "$arg" = "--no-wait" ]; then
        wait_between_tiers=false
    fi
done

show_status() {
    printf "%-30s %-10s %-10s\n" "SERVICE" "ACTIVE" "SUB"
    printf "%-30s %-10s %-10s\n" "-------" "------" "---"
    for svc in "${ALL[@]}"; do
        active=$(systemctl --user is-active "${svc}.service" 2>/dev/null || echo "?")
        sub=$(systemctl --user show -p SubState --value "${svc}.service" 2>/dev/null || echo "?")
        printf "%-30s %-10s %-10s\n" "$svc" "$active" "$sub"
    done
}

restart_tier() {
    local tier_name="$1"
    shift
    echo "[$tier_name] restarting: $*"
    for svc in "$@"; do
        if systemctl --user list-unit-files "${svc}.service" >/dev/null 2>&1; then
            echo "  → ${svc}"
            systemctl --user restart "${svc}.service" || {
                echo "    !! ${svc} failed to restart; check: journalctl --user -u ${svc}.service -n 30"
            }
        else
            echo "  ?? ${svc} not installed; skipping"
        fi
    done
}

if [ "$action" = "status" ]; then
    show_status
    exit 0
fi

echo "[soveryn-restart] starting full stack restart at $(date -Iseconds)"

restart_tier "foundation" "${FOUNDATION[@]}"
if $wait_between_tiers; then
    echo "[soveryn-restart] waiting 15s for foundation services to be ready..."
    sleep 15
fi

restart_tier "app" "${APP[@]}"
if $wait_between_tiers; then
    echo "[soveryn-restart] waiting 5s for app to come up..."
    sleep 5
fi

restart_tier "background" "${BACKGROUND[@]}"

echo ""
echo "[soveryn-restart] done. final state:"
show_status
