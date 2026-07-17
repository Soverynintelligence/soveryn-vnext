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

import json
import subprocess
import time
import urllib.error
import urllib.request
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


# ── probe classification (pure) ─────────────────────────────────────────────
_HTTP_PORTS = {"vnext": 5001, "embeddings": 8096, "router": 8090}
_UNIT_KEYS = ("dream", "x-feed", "tg-bridge", "parakeet", "vett-patrol", "representation")


def probe_unhealthy(
    *,
    http_ok: dict[str, bool],
    unit_active: dict[str, bool],
    heartbeat_age: float,
    comfyui_on_her_card: bool,
) -> tuple[set[str], bool]:
    """Pure: turn injected readings into (unhealthy_keys, router_healthy)."""
    unhealthy: set[str] = set()
    if not http_ok.get("vnext", True):
        unhealthy.add("vnext")
    if not http_ok.get("embeddings", True):
        unhealthy.add("embeddings")
    for key in _UNIT_KEYS:
        if not unit_active.get(key, True):
            unhealthy.add(key)
    if heartbeat_age > HEARTBEAT_MAX_AGE_S:
        unhealthy.add("heartbeat")
    if comfyui_on_her_card:
        unhealthy.add("comfyui")
    return unhealthy, bool(http_ok.get("router", True))


# ── live readers ────────────────────────────────────────────────────────────
def _http_ok(port: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError):
        return False


def _unit_is_active(unit: str, timeout: float = 3.0) -> bool:
    try:
        out = subprocess.run(["systemctl", "--user", "is-active", unit],
                             capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() == "active"
    except (subprocess.SubprocessError, OSError):
        return False  # can't confirm alive → treat as unhealthy (medic will restart)


def _heartbeat_age(now: float) -> float:
    try:
        return now - HEARTBEAT_FILE.stat().st_mtime
    except OSError:
        return 0.0  # unknown → do not fire a false heartbeat alarm


def _comfyui_on_her_card() -> bool:
    from soveryn.agents.ares.lanes import vitals
    try:
        apps = vitals._read_compute_apps()
    except Exception:  # noqa: BLE001
        return False
    return any(gpu == vitals.HER_GPU_UUID and "envs/comfyui/" in name
               for gpu, _pid, name in apps)


def _probe() -> tuple[set[str], bool]:
    now = time.time()
    http_ok = {k: _http_ok(p) for k, p in _HTTP_PORTS.items()}
    unit_active = {k: _unit_is_active(TARGETS[k].unit) for k in _UNIT_KEYS}
    return probe_unhealthy(
        http_ok=http_ok,
        unit_active=unit_active,
        heartbeat_age=_heartbeat_age(now),
        comfyui_on_her_card=_comfyui_on_her_card(),
    )


# ── actuation + state ───────────────────────────────────────────────────────
def _run_unit(unit: str, verb: str) -> None:
    if unit in FORBIDDEN_UNITS:  # belt-and-suspenders; no router target exists
        raise AssertionError(f"medic refused to {verb} forbidden unit {unit}")
    subprocess.run(["systemctl", "--user", verb, unit], timeout=90, check=True)


def _escalate(decision: MedicDecision) -> None:
    signal_sender.send(f"[MEDIC] {decision.unit} {decision.reason}", priority=decision.priority)


def _read_history() -> dict[str, list[float]]:
    try:
        return {k: [float(t) for t in v] for k, v in json.loads(HISTORY_FILE.read_text()).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _write_history(history: dict[str, list[float]], now: float) -> None:
    pruned = {k: [t for t in v if now - t < LOOPGUARD_WINDOW_S] for k, v in history.items()}
    pruned = {k: v for k, v in pruned.items() if v}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(pruned, sort_keys=True))


def _log(record: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def run_once(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    unhealthy, router_healthy = _probe()
    history = _read_history()
    decisions = decide(unhealthy_keys=unhealthy, router_healthy=router_healthy,
                       restart_history=history, now=now)
    actions = []
    for d in decisions:
        if d.action == "act":
            _run_unit(d.unit, TARGETS[d.key].verb)
            history.setdefault(d.key, []).append(now)
        elif d.action == "escalate":
            _escalate(d)
        actions.append({"key": d.key, "unit": d.unit, "action": d.action, "reason": d.reason})
    _write_history(history, now)
    _log({"ts": now, "unhealthy": sorted(unhealthy), "router_healthy": router_healthy, "actions": actions})
    return {"unhealthy": sorted(unhealthy), "actions": actions}
