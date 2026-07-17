"""Medic — the fleet's auto-heal actuator.

Cloned in shape from platform/watchdog/router_watchdog.py: pure decision core
(`decide`) + thin systemctl/urllib shell (`run_once`), file-based PER-TARGET
cooldown, JSONL audit. It restarts green-healable units and, when a heal fails
repeatedly (loop-guard), escalates to Signal instead of restarting forever.

HARD INVARIANT: the medic never restarts a router. Routers are owned by
router_watchdog; two actuators fighting over one unit is how you get a restart
loop. `FORBIDDEN_UNITS` + a test enforce this.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from soveryn.agents.ares import signal_sender

STATE_DIR = Path.home() / "soveryn_vnext" / "data" / "medic"
HISTORY_FILE = STATE_DIR / "restart_history.json"
LOG_FILE = STATE_DIR / "medic.jsonl"

HEARTBEAT_FILE = Path.home() / "soveryn_vnext" / "data" / "heartbeat_thoughts.jsonl"
HEARTBEAT_MAX_AGE_S = 2400.0   # 40 min — one missed 30-min beat + margin

LOOPGUARD_MAX = 3
LOOPGUARD_WINDOW_S = 900.0

FORBIDDEN_UNITS = {"soveryn-router.service", "soveryn-router-quadro.service"}


@dataclass(frozen=True)
class MedicTarget:
    key: str
    unit: str
    cooldown_s: float
    escalation_priority: bool  # True → EMERGENCY (bypasses Signal quiet hours)
    verb: str = "restart"      # "restart" | "stop" (comfyui is stopped, not restarted)


@dataclass(frozen=True)
class MedicDecision:
    key: str
    unit: str
    action: str   # "act" | "escalate" | "skip_cooldown" | "skip_router_down"
    reason: str
    priority: bool = False


TARGETS: dict[str, MedicTarget] = {
    "vnext":      MedicTarget("vnext", "soveryn-vnext.service", 300.0, escalation_priority=True),
    "embeddings": MedicTarget("embeddings", "soveryn-embeddings.service", 300.0, escalation_priority=False),
    "heartbeat":  MedicTarget("heartbeat", "soveryn-heartbeat.service", 600.0, escalation_priority=False),
    "dream":      MedicTarget("dream", "soveryn-dream.service", 300.0, escalation_priority=False),
    "x-feed":     MedicTarget("x-feed", "soveryn-x-feed.service", 300.0, escalation_priority=False),
    "tg-bridge":  MedicTarget("tg-bridge", "soveryn-tg-bridge.service", 300.0, escalation_priority=False),
    "parakeet":   MedicTarget("parakeet", "parakeet.service", 300.0, escalation_priority=False),
    "vett-patrol": MedicTarget("vett-patrol", "soveryn-vett-patrol.service", 300.0, escalation_priority=False),
    "representation": MedicTarget("representation", "soveryn-representation.service", 300.0, escalation_priority=False),
    "comfyui":    MedicTarget("comfyui", "soveryn-comfyui.service", 600.0, escalation_priority=False, verb="stop"),
}


def decide(
    *,
    unhealthy_keys: set[str],
    router_healthy: bool,
    restart_history: dict[str, list[float]],
    now: float,
    targets: dict[str, MedicTarget] = TARGETS,
    loopguard_max: int = LOOPGUARD_MAX,
    loopguard_window_s: float = LOOPGUARD_WINDOW_S,
) -> list[MedicDecision]:
    """Pure. One decision per unhealthy target, in deterministic key order."""
    decisions: list[MedicDecision] = []
    for key in sorted(unhealthy_keys):
        target = targets[key]
        if key == "vnext" and not router_healthy:
            decisions.append(MedicDecision(key, target.unit, "skip_router_down",
                                           "router unhealthy; not restarting vnext"))
            continue
        history = restart_history.get(key, [])
        recent = [ts for ts in history if now - ts < loopguard_window_s]
        if len(recent) >= loopguard_max:
            decisions.append(MedicDecision(key, target.unit, "escalate",
                                           f"unhealed after {loopguard_max} attempts in {int(loopguard_window_s)}s",
                                           priority=target.escalation_priority))
            continue
        last = max(history) if history else None
        if last is not None and (now - last) < target.cooldown_s:
            decisions.append(MedicDecision(key, target.unit, "skip_cooldown",
                                           f"within {int(target.cooldown_s)}s cooldown"))
            continue
        decisions.append(MedicDecision(key, target.unit, "act", "unhealthy — healing"))
    return decisions
