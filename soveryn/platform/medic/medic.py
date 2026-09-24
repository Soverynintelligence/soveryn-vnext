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
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from soveryn.agents.ares import signal_sender

STATE_DIR = Path.home() / "soveryn_vnext" / "data" / "medic"
STATE_FILE = STATE_DIR / "medic_state.json"
LOG_FILE = STATE_DIR / "medic.jsonl"

# Liveness comes from heartbeat_log (a row EVERY ~30-min tick, including
# quiet-hours skips) — NOT the thoughts file, which only moves when she
# produces a thought. A resting heartbeat still ticks; it is not a glitch.
HEARTBEAT_LOG_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
HEARTBEAT_MAX_AGE_S = 2400.0   # 40 min — one missed 30-min beat + margin

LOOPGUARD_MAX = 3

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
    action: str   # "act" | "escalate" | "skip_cooldown" | "skip_router_down" | "skip_escalated"
    reason: str
    priority: bool = False


TARGETS: dict[str, MedicTarget] = {
    "vnext":      MedicTarget("vnext", "soveryn-vnext.service", 300.0, escalation_priority=True),
    # embeddings: helper Quadro soveryn-embeddings.service (:8096). Spark
    # soveryn-embed stays disabled — GLM owns that UMA.
    "embeddings": MedicTarget("embeddings", "soveryn-embeddings.service", 300.0, escalation_priority=False),
    "heartbeat":  MedicTarget("heartbeat", "soveryn-heartbeat.service", 600.0, escalation_priority=False),
    "dream":      MedicTarget("dream", "soveryn-dream.service", 300.0, escalation_priority=False),
    "x-feed":     MedicTarget("x-feed", "soveryn-x-feed.service", 300.0, escalation_priority=False),
    # tg-bridge RETIRED 2026-08-07. Telegram was replaced by Signal; the bridge
    # had been logging 91,560 HTTP 409s in 7 days because the Claude Code
    # telegram plugin polls the same bot token and Telegram permits one
    # getUpdates consumer. `systemctl disable --now` did not hold: the medic saw
    # a stopped unit, called it unhealthy, and restarted it 42s later. A medic
    # cannot distinguish "deliberately retired" from "crashed" — the watch list
    # is the only place that distinction can live, so it is removed here.
    "parakeet":   MedicTarget("parakeet", "parakeet.service", 300.0, escalation_priority=False),
    "vett-patrol": MedicTarget("vett-patrol", "soveryn-vett-patrol.service", 300.0, escalation_priority=False),
    "representation": MedicTarget("representation", "soveryn-representation.service", 300.0, escalation_priority=False),
    "comfyui":    MedicTarget("comfyui", "soveryn-comfyui.service", 600.0, escalation_priority=False, verb="stop"),
}


def decide(
    *,
    unhealthy_keys: set[str],
    router_healthy: bool,
    state: dict[str, dict],
    now: float,
    targets: dict[str, MedicTarget] = TARGETS,
    loopguard_max: int = LOOPGUARD_MAX,
) -> list[MedicDecision]:
    """Pure. One decision per unhealthy target, in deterministic key order.

    Convergence: a target is restarted (cooldown-paced) up to loopguard_max
    times; after that it is escalated ONCE (latched via state["escalated"]) and
    then left alone until it recovers. run_once clears a target's state the tick
    it is no longer unhealthy, so a healed service resets cleanly.
    """
    decisions: list[MedicDecision] = []
    for key in sorted(unhealthy_keys):
        # Keys probed but not in TARGETS — no local unit. Page once, then latch
        # (same as TARGET skip_escalated). Without the latch, a parked remote
        # (Spark embed) Signal-spammed every 60s timer tick.
        if key not in targets:
            st = state.get(key, _blank_state())
            if st["escalated"]:
                decisions.append(MedicDecision(
                    key, "remote", "skip_escalated",
                    "already escalated; awaiting recovery",
                ))
            else:
                decisions.append(MedicDecision(
                    key, "remote", "escalate",
                    "unhealthy remote surface (no tower unit)",
                    priority=False,
                ))
            continue
        target = targets[key]
        if key == "vnext" and not router_healthy:
            decisions.append(MedicDecision(key, target.unit, "skip_router_down",
                                           "router unhealthy; not restarting vnext"))
            continue
        st = state.get(key, _blank_state())
        if st["escalated"]:
            decisions.append(MedicDecision(key, target.unit, "skip_escalated",
                                           "already escalated; awaiting recovery"))
            continue
        if st["consecutive_fails"] >= loopguard_max:
            decisions.append(MedicDecision(key, target.unit, "escalate",
                                           f"unhealed after {loopguard_max} restart attempts",
                                           priority=target.escalation_priority))
            continue
        last = st["last_restart_ts"]
        if last is not None and (now - last) < target.cooldown_s:
            decisions.append(MedicDecision(key, target.unit, "skip_cooldown",
                                           f"within {int(target.cooldown_s)}s cooldown"))
            continue
        decisions.append(MedicDecision(key, target.unit, "act", "unhealthy — healing"))
    return decisions


# ── probe classification (pure) ─────────────────────────────────────────────
_HTTP_PORTS = {"vnext": 5001, "router": 8090}
_HTTP_URLS: dict[str, str] = {"embeddings": "http://127.0.0.1:8096/health"}
_UNIT_KEYS = ("dream", "x-feed", "parakeet", "vett-patrol", "representation")


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


def _http_url_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
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


def _heartbeat_age(now: float, db_path: Path = HEARTBEAT_LOG_DB) -> float:
    """Seconds since the heartbeat daemon last TICKED (per heartbeat_log,
    which logs every tick incl. quiet-hours skips). 0.0 on any error —
    unknown liveness must not trigger a restart."""
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT MAX(triggered_at) FROM heartbeat_log").fetchone()
        finally:
            conn.close()
        if not row or not row[0]:
            return 0.0
        return now - datetime.fromisoformat(row[0]).timestamp()
    except Exception:  # noqa: BLE001 — unknown liveness is not a stale alarm
        return 0.0


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
    http_ok.update({k: _http_url_ok(u) for k, u in _HTTP_URLS.items()})
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


def _blank_state() -> dict:
    return {"consecutive_fails": 0, "last_restart_ts": None, "escalated": False}


def _read_state() -> dict[str, dict]:
    try:
        raw = json.loads(STATE_FILE.read_text())
        return {
            k: {
                "consecutive_fails": int(v.get("consecutive_fails", 0)),
                "last_restart_ts": (float(v["last_restart_ts"]) if v.get("last_restart_ts") is not None else None),
                "escalated": bool(v.get("escalated", False)),
            }
            for k, v in raw.items()
        }
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _write_state(state: dict[str, dict]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, sort_keys=True))


def _log(record: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def run_once(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    unhealthy, router_healthy = _probe()
    state = _read_state()
    # Recovery: forget any target no longer unhealthy — clears its fail count
    # AND its escalation latch, so the next outage starts fresh.
    for key in list(state):
        if key not in unhealthy:
            del state[key]
    decisions = decide(unhealthy_keys=unhealthy, router_healthy=router_healthy,
                       state=state, now=now)
    actions = []
    for d in decisions:
        record = {"key": d.key, "unit": d.unit, "action": d.action, "reason": d.reason}
        if d.action == "act":
            st = state.setdefault(d.key, _blank_state())
            try:
                _run_unit(d.unit, TARGETS[d.key].verb)
                record["ok"] = True
            except Exception as exc:  # noqa: BLE001 — a failed heal must not abort the tick
                record["ok"] = False
                record["error"] = str(exc)
            st["consecutive_fails"] += 1
            st["last_restart_ts"] = now
        elif d.action == "escalate":
            st = state.setdefault(d.key, _blank_state())
            try:
                _escalate(d)
                record["ok"] = True
            except Exception as exc:  # noqa: BLE001 — a failed page must not abort the tick
                record["ok"] = False
                record["error"] = str(exc)
            st["escalated"] = True  # latch: page once, then stay quiet until recovery
        actions.append(record)
    _write_state(state)
    _log({"ts": now, "unhealthy": sorted(unhealthy), "router_healthy": router_healthy, "actions": actions})
    return {"unhealthy": sorted(unhealthy), "actions": actions}
