# Vital Signs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the SOVERYN fleet a deterministic outside-the-LLM health layer: an Ares *vitals lane* that detects human-remedy red conditions and a separate *medic* actuator that auto-heals reversible failures and pages Jon on the rest.

**Architecture:** Two disjoint units that each read reality independently, no shared mutable state. (1) A new Ares collector `collect_vitals_live` (GPU headroom, foreign process on her card, stuck delegation) reusing the existing `AresFinding` → tracker → severity-router → Signal pipeline — detection only, mutates nothing. (2) A new `soveryn.platform.medic` actuator cloned from `router_watchdog.py` (pure decision core + thin `systemctl` shell, per-target cooldown, JSONL audit, oneshot `.service` + 60s `.timer`) that restarts green-healable units and escalates to Signal on heal failure. The medic NEVER touches router units (the existing watchdog owns those).

**Tech Stack:** Python 3.11 (soveryn conda env), stdlib only (`subprocess`, `urllib`, `sqlite3`, `datetime`), pytest, systemd user units. Reuses `soveryn.agents.ares.findings`, `soveryn.agents.ares.signal_sender`.

## Global Constraints

- **Python:** run everything with `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python` (3.11), NOT base 3.13. Run tests from repo root `/home/jon-deoliveira/soveryn_vnext`.
- **Cards keyed by UUID, never index.** Her Blackwell UUID = `GPU-946b08b0-e9d3-949b-6eab-b6c5b8a5f5cd`, overridable via env `ARES_HER_GPU_UUID`.
- **The medic NEVER restarts `soveryn-router.service` or `soveryn-router-quadro.service`** — asserted by a test. The existing `router_watchdog` owns router recovery.
- **Ares is detection-only.** The vitals lane must not start/stop/kill/write anything; every probe fails safe (returns `[]` on error) so a probe failure never crashes the Ares daemon.
- **No active TTFT probe** (measured: `:8091` cold = 4.8 s → false alarms; repeats a reverted mistake).
- **Set-points (exact):** her-card free VRAM < 2048 MB → EMERGENCY, < 3072 MB → WARNING; other card free < 1024 MB → CRITICAL; heartbeat age > 2400 s (40 min); delegation `executing` age > 360 s; medic loop-guard = 3 restarts of one target within 900 s → escalate; cooldowns: vnext/embeddings/non-critical services 300 s, heartbeat/comfyui 600 s.
- **Severity → paging:** EMERGENCY bypasses Signal quiet hours (23:00–07:00); CRITICAL respects them; WARNING/INFO never page (bus/telemetry only). This is already enforced by `soveryn/agents/ares/router.py` and `signal_sender.py` — do not re-implement it.
- **Deferred from spec (do NOT build):** the her-card thermal → EMERGENCY severity bump. It requires threading UUID through the shared `collect_gpu` (changing its 7-field row contract and its existing tests) for a nicety already backstopped by the "her router down > 5 min → EMERGENCY" path. Her-card thermal stays CRITICAL (existing behavior). Flagged to Jon.

---

## File Structure

- **Create** `soveryn/agents/ares/lanes/vitals.py` — vitals collector: pure decision functions (`collect_gpu_headroom`, `collect_foreign_procs`, `collect_delegation_stuck`) + zero-arg live wrapper `collect_vitals_live`.
- **Modify** `soveryn/agents/ares/daemon.py` — import `collect_vitals_live` (line ~19) and append it to `_default_collectors()` (line ~145).
- **Create** `soveryn/platform/medic/__init__.py` — package marker + re-exports.
- **Create** `soveryn/platform/medic/medic.py` — pure decision core (`MedicTarget`, `MedicDecision`, `TARGETS`, `FORBIDDEN_UNITS`, `decide`) + I/O shell (`run_once` and its helpers).
- **Create** `soveryn/platform/medic/__main__.py` — `python -m soveryn.platform.medic` entry that calls `run_once()`.
- **Create** `runtime/soveryn-medic.service`, `runtime/soveryn-medic.timer` — repo copies of the systemd user units.
- **Test** `tests/test_ares_vitals_lane.py`, `tests/test_medic.py`.

---

## Task 1: Ares vitals lane — pure decision functions

**Files:**
- Create: `soveryn/agents/ares/lanes/vitals.py`
- Test: `tests/test_ares_vitals_lane.py`

**Interfaces:**
- Consumes: `AresFinding`, `Severity` from `soveryn.agents.ares.findings`.
- Produces:
  - `HER_GPU_UUID: str`
  - `HeadroomThresholds` dataclass with `.from_env()`
  - `collect_gpu_headroom(rows: list[tuple[str,int,int]], *, her_uuid: str = HER_GPU_UUID, thresholds: HeadroomThresholds | None = None) -> list[AresFinding]` — rows are `(uuid, used_mb, total_mb)`.
  - `collect_foreign_procs(apps: list[tuple[str,str,str]], *, her_uuid: str = HER_GPU_UUID) -> list[AresFinding]` — apps are `(gpu_uuid, pid, process_name)`.
  - `collect_delegation_stuck(tasks: list[tuple[str,str,float]], *, now: float, max_executing_seconds: int = 360) -> list[AresFinding]` — tasks are `(task_id, status, updated_at_epoch)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ares_vitals_lane.py
from soveryn.agents.ares.findings import Severity
from soveryn.agents.ares.lanes import vitals

HER = vitals.HER_GPU_UUID
OTHER = "GPU-0000other0000"


def _by_type(findings):
    return {f.finding_type: f for f in findings}


def test_her_card_low_headroom_is_emergency():
    # her card: total 48935, used 47500 → free 1435 < 2048
    out = vitals.collect_gpu_headroom([(HER, 47500, 48935)])
    assert len(out) == 1
    assert out[0].finding_type == "gpu.headroom"
    assert out[0].severity == Severity.EMERGENCY
    assert out[0].evidence["free_mb"] == 1435
    assert out[0].key == HER


def test_her_card_early_warn_headroom_is_warning():
    # free 2800 → between 2048 and 3072 → WARNING
    out = vitals.collect_gpu_headroom([(HER, 46135, 48935)])
    assert out[0].severity == Severity.WARNING


def test_her_card_healthy_headroom_emits_nothing():
    # free 5800 → healthy → no finding (recovery handled by tracker clear)
    assert vitals.collect_gpu_headroom([(HER, 43135, 48935)]) == []


def test_other_card_low_headroom_is_critical():
    out = vitals.collect_gpu_headroom([(OTHER, 48500, 49152)])  # free 652 < 1024
    assert out[0].severity == Severity.CRITICAL


def test_foreign_proc_non_comfyui_on_her_card_is_critical():
    apps = [(HER, "999", "/home/jon-deoliveira/miniconda3/envs/f5tts/bin/python")]
    out = vitals.collect_foreign_procs(apps)
    assert out[0].finding_type == "gpu.foreign_proc"
    assert out[0].severity == Severity.CRITICAL
    assert out[0].evidence["evictable_comfyui"] is False


def test_comfyui_on_her_card_is_warning_and_evictable():
    apps = [(HER, "999", "/home/jon-deoliveira/miniconda3/envs/comfyui/bin/python")]
    out = vitals.collect_foreign_procs(apps)
    assert out[0].severity == Severity.WARNING
    assert out[0].evidence["evictable_comfyui"] is True


def test_her_llama_server_and_other_card_procs_are_ignored():
    apps = [
        (HER, "100", "/home/jon-deoliveira/llama.cpp_head/build/bin/llama-server"),  # hers
        (OTHER, "200", "/home/jon-deoliveira/miniconda3/envs/f5tts/bin/python"),      # not her card
    ]
    assert vitals.collect_foreign_procs(apps) == []


def test_delegation_stuck_fires_past_threshold():
    tasks = [("t1", "executing", 1000.0)]
    out = vitals.collect_delegation_stuck(tasks, now=1400.0)  # age 400 > 360
    assert out[0].finding_type == "delegation.stuck"
    assert out[0].severity == Severity.WARNING
    assert out[0].key == "t1"


def test_delegation_recent_or_terminal_is_ignored():
    tasks = [
        ("t1", "executing", 1300.0),  # age 100 < 360
        ("t2", "failed", 1.0),         # terminal
    ]
    assert vitals.collect_delegation_stuck(tasks, now=1400.0) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_ares_vitals_lane.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'soveryn.agents.ares.lanes.vitals'`

- [ ] **Step 3: Write the pure decision functions**

```python
# soveryn/agents/ares/lanes/vitals.py
"""Ares vitals lane — deterministic fleet-health detection (detection-only).

Adds the signals the existing hardware lane doesn't cover: GPU VRAM headroom
(collected but never thresholded before), a foreign process on Aetheria's card,
and a stuck delegation task. Emits AresFindings; mutates nothing. Every live
probe fails safe (returns []) so a probe error never crashes the Ares daemon.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from soveryn.agents.ares.findings import AresFinding, Severity

#: Aetheria's Blackwell. Keyed by UUID because the CX-7 install renumbered PCI
#: once — CUDA order survived, PCI did not. Override via env for tests/moves.
HER_GPU_UUID = os.environ.get(
    "ARES_HER_GPU_UUID", "GPU-946b08b0-e9d3-949b-6eab-b6c5b8a5f5cd"
)

DELEGATION_DB = Path.home() / "soveryn_vnext" / "data" / "delegation.db"


@dataclass(frozen=True)
class HeadroomThresholds:
    her_emergency_free_mb: int = 2048
    her_warning_free_mb: int = 3072
    other_critical_free_mb: int = 1024

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "HeadroomThresholds":
        env = env or os.environ
        return cls(
            her_emergency_free_mb=int(env.get("ARES_HER_GPU_EMERGENCY_FREE_MB", "2048")),
            her_warning_free_mb=int(env.get("ARES_HER_GPU_WARNING_FREE_MB", "3072")),
            other_critical_free_mb=int(env.get("ARES_GPU_CRITICAL_FREE_MB", "1024")),
        )


def collect_gpu_headroom(
    rows: list[tuple[str, int, int]],
    *,
    her_uuid: str = HER_GPU_UUID,
    thresholds: HeadroomThresholds | None = None,
) -> list[AresFinding]:
    """rows = [(uuid, used_mb, total_mb)]. Emits a finding only when a card
    breaches its floor; healthy cards emit nothing (the tracker clears the
    prior finding on recovery)."""
    thresholds = thresholds or HeadroomThresholds.from_env()
    findings: list[AresFinding] = []
    for uuid, used, total in rows:
        free = total - used
        evidence = {"uuid": uuid, "used_mb": used, "total_mb": total, "free_mb": free}
        if uuid == her_uuid:
            if free < thresholds.her_emergency_free_mb:
                findings.append(AresFinding("gpu.headroom", Severity.EMERGENCY, evidence, key=uuid))
            elif free < thresholds.her_warning_free_mb:
                findings.append(AresFinding("gpu.headroom", Severity.WARNING, evidence, key=uuid))
        else:
            if free < thresholds.other_critical_free_mb:
                findings.append(AresFinding("gpu.headroom", Severity.CRITICAL, evidence, key=uuid))
    return findings


def collect_foreign_procs(
    apps: list[tuple[str, str, str]],
    *,
    her_uuid: str = HER_GPU_UUID,
) -> list[AresFinding]:
    """apps = [(gpu_uuid, pid, process_name)]. Flags any process on HER card
    that isn't her llama-server. comfyui is WARNING+evictable (the medic may
    stop it); anything else is CRITICAL (page — could be f5tts/voice)."""
    findings: list[AresFinding] = []
    for gpu_uuid, pid, process_name in apps:
        if gpu_uuid != her_uuid:
            continue
        name = process_name.strip()
        if "llama-server" in name:
            continue  # hers
        is_comfyui = "envs/comfyui/" in name
        findings.append(AresFinding(
            "gpu.foreign_proc",
            Severity.WARNING if is_comfyui else Severity.CRITICAL,
            {"uuid": gpu_uuid, "pid": pid, "process_name": name, "evictable_comfyui": is_comfyui},
            key=f"{gpu_uuid}:{name}",
        ))
    return findings


def collect_delegation_stuck(
    tasks: list[tuple[str, str, float]],
    *,
    now: float,
    max_executing_seconds: int = 360,
) -> list[AresFinding]:
    """tasks = [(task_id, status, updated_at_epoch)]. A task stuck in
    'executing' past the acceptance timeout is a WARNING (alert-only — never
    auto-touch Scotty's state)."""
    findings: list[AresFinding] = []
    for task_id, status, updated_epoch in tasks:
        if status != "executing":
            continue
        age = now - updated_epoch
        if age > max_executing_seconds:
            findings.append(AresFinding(
                "delegation.stuck",
                Severity.WARNING,
                {"task_id": task_id, "age_seconds": round(age, 1)},
                key=task_id,
            ))
    return findings
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_ares_vitals_lane.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/ares/lanes/vitals.py tests/test_ares_vitals_lane.py
git commit -m "feat(ares): vitals lane pure detection functions (headroom/foreign-proc/delegation)"
```

---

## Task 2: Vitals lane live wrapper + daemon registration

**Files:**
- Modify: `soveryn/agents/ares/lanes/vitals.py` (append live helpers + `collect_vitals_live`)
- Modify: `soveryn/agents/ares/daemon.py:19` (import) and `soveryn/agents/ares/daemon.py:145-151` (register)
- Test: `tests/test_ares_vitals_lane.py` (append)

**Interfaces:**
- Consumes: the Task 1 pure functions.
- Produces: `collect_vitals_live() -> list[AresFinding]` — zero positional args (satisfies the `Collector = Callable[[], Iterable[AresFinding]]` contract in `daemon.py:36`). Reads live `nvidia-smi` and `delegation.db`; fails safe to `[]` per source on any error.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_ares_vitals_lane.py
from soveryn.agents.ares import daemon as ares_daemon


def test_parse_gpu_headroom_rows_parses_csv():
    csv = "GPU-abc, 47500, 48935\nGPU-def, 100, 49152\n"
    assert vitals._parse_gpu_headroom_rows(csv) == [("GPU-abc", 47500, 48935), ("GPU-def", 100, 49152)]


def test_parse_compute_apps_parses_csv():
    csv = "GPU-abc, 999, /x/envs/comfyui/bin/python\n"
    assert vitals._parse_compute_apps(csv) == [("GPU-abc", "999", "/x/envs/comfyui/bin/python")]


def test_collect_vitals_live_is_zero_arg_and_safe(monkeypatch):
    # Force every underlying reader to raise; the lane must swallow and return [].
    monkeypatch.setattr(vitals, "_read_gpu_headroom_rows", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(vitals, "_read_compute_apps", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(vitals, "_read_executing_tasks", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert vitals.collect_vitals_live() == []


def test_vitals_lane_is_registered_in_default_collectors():
    collectors = ares_daemon._default_collectors()
    assert vitals.collect_vitals_live in collectors
    # And it honors the zero-arg collector contract.
    assert callable(vitals.collect_vitals_live)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_ares_vitals_lane.py -q -k "live or registered or parse_gpu_headroom or compute_apps"`
Expected: FAIL with `AttributeError: module 'soveryn.agents.ares.lanes.vitals' has no attribute '_parse_gpu_headroom_rows'`

- [ ] **Step 3: Add the live wrapper**

Append to `soveryn/agents/ares/lanes/vitals.py`:

```python
# ── live I/O shell (fails safe per source) ──────────────────────────────────
def _parse_gpu_headroom_rows(csv_text: str) -> list[tuple[str, int, int]]:
    rows: list[tuple[str, int, int]] = []
    for line in csv_text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            rows.append((parts[0], int(parts[1]), int(parts[2])))
        except ValueError:
            continue
    return rows


def _parse_compute_apps(csv_text: str) -> list[tuple[str, str, str]]:
    apps: list[tuple[str, str, str]] = []
    for line in csv_text.splitlines():
        parts = [p.strip() for p in line.split(",", 2)]
        if len(parts) != 3:
            continue
        apps.append((parts[0], parts[1], parts[2]))
    return apps


def _read_gpu_headroom_rows() -> list[tuple[str, int, int]]:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=uuid,memory.used,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=5,
    )
    return _parse_gpu_headroom_rows(out.stdout) if out.returncode == 0 else []


def _read_compute_apps() -> list[tuple[str, str, str]]:
    out = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,process_name",
         "--format=csv,noheader"],
        capture_output=True, text=True, timeout=5,
    )
    return _parse_compute_apps(out.stdout) if out.returncode == 0 else []


def _read_executing_tasks(db_path: Path = DELEGATION_DB) -> list[tuple[str, str, float]]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT id, status, updated_at FROM delegation_tasks WHERE status = 'executing'"
        ).fetchall()
    finally:
        conn.close()
    tasks: list[tuple[str, str, float]] = []
    for task_id, status, updated_at in rows:
        try:
            epoch = datetime.fromisoformat(updated_at).timestamp()
        except (ValueError, TypeError):
            continue
        tasks.append((str(task_id), str(status), epoch))
    return tasks


def _safe(reader, transform):
    try:
        return transform(reader())
    except Exception:  # noqa: BLE001 — detection must never crash the daemon
        return []


def collect_vitals_live() -> list[AresFinding]:
    """Zero-arg Ares collector. Each source is independently fail-safe."""
    now = time.time()
    findings: list[AresFinding] = []
    findings += _safe(_read_gpu_headroom_rows, collect_gpu_headroom)
    findings += _safe(_read_compute_apps, collect_foreign_procs)
    findings += _safe(_read_executing_tasks, lambda tasks: collect_delegation_stuck(tasks, now=now))
    return findings
```

- [ ] **Step 4: Register in the daemon**

In `soveryn/agents/ares/daemon.py`, change the hardware-lane import line (currently line 19):

```python
from soveryn.agents.ares.lanes.hardware import collect_cpu_live, collect_drives_live, collect_gpu_live
from soveryn.agents.ares.lanes.vitals import collect_vitals_live
```

And append to `_default_collectors()` (currently lines 145-151):

```python
def _default_collectors() -> tuple[Collector, ...]:
    return (
        collect_gpu_live,
        collect_cpu_live,
        collect_drives_live,
        collect_network_live,
        collect_architecture_live,
        collect_vitals_live,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_ares_vitals_lane.py tests/test_ares_daemon.py -q`
Expected: PASS (all vitals tests + existing daemon tests still green)

- [ ] **Step 6: Commit**

```bash
git add soveryn/agents/ares/lanes/vitals.py soveryn/agents/ares/daemon.py tests/test_ares_vitals_lane.py
git commit -m "feat(ares): wire collect_vitals_live into the daemon collector set"
```

---

## Task 3: Medic decision core (pure) + collision guard

**Files:**
- Create: `soveryn/platform/medic/__init__.py`
- Create: `soveryn/platform/medic/medic.py` (decision core only in this task)
- Test: `tests/test_medic.py`

**Interfaces:**
- Produces:
  - `MedicTarget(key: str, unit: str, cooldown_s: float, escalation_priority: bool, verb: str = "restart")`
  - `MedicDecision(key: str, unit: str, action: str, reason: str, priority: bool = False)` — `action ∈ {"act", "escalate", "skip_cooldown", "skip_router_down"}`.
  - `TARGETS: dict[str, MedicTarget]`
  - `FORBIDDEN_UNITS: set[str]`
  - `decide(*, unhealthy_keys: set[str], router_healthy: bool, restart_history: dict[str, list[float]], now: float, targets: dict[str, MedicTarget] = TARGETS, loopguard_max: int = 3, loopguard_window_s: float = 900.0) -> list[MedicDecision]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_medic.py
from soveryn.platform.medic import medic


def test_no_target_is_a_router_unit():
    # HARD SAFETY INVARIANT: the medic must never be able to restart a router.
    target_units = {t.unit for t in medic.TARGETS.values()}
    assert medic.FORBIDDEN_UNITS.isdisjoint(target_units)
    assert "soveryn-router.service" in medic.FORBIDDEN_UNITS
    assert "soveryn-router-quadro.service" in medic.FORBIDDEN_UNITS


def test_unhealthy_target_out_of_cooldown_acts():
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     restart_history={}, now=1000.0)
    assert len(d) == 1 and d[0].action == "act" and d[0].unit == "soveryn-embeddings.service"


def test_within_cooldown_is_skipped():
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     restart_history={"embeddings": [900.0]}, now=1000.0)  # 100 < 300
    assert d[0].action == "skip_cooldown"


def test_cooldown_is_per_target_not_global():
    # embeddings cooling, heartbeat not → heartbeat still acts.
    d = medic.decide(unhealthy_keys={"embeddings", "heartbeat"}, router_healthy=True,
                     restart_history={"embeddings": [990.0]}, now=1000.0)
    by_key = {x.key: x for x in d}
    assert by_key["embeddings"].action == "skip_cooldown"
    assert by_key["heartbeat"].action == "act"


def test_loopguard_trips_to_escalate():
    hist = {"vnext": [100.0, 400.0, 700.0]}  # 3 restarts within 900s of now=800
    d = medic.decide(unhealthy_keys={"vnext"}, router_healthy=True,
                     restart_history=hist, now=800.0)
    assert d[0].action == "escalate"
    assert d[0].priority is True  # vnext escalation is night-pageable


def test_loopguard_window_expires():
    hist = {"embeddings": [0.0, 10.0, 20.0]}  # all older than 900s at now=2000
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     restart_history=hist, now=2000.0)
    assert d[0].action == "act"


def test_vnext_deferred_when_router_unhealthy():
    d = medic.decide(unhealthy_keys={"vnext"}, router_healthy=False,
                     restart_history={}, now=1000.0)
    assert d[0].action == "skip_router_down"


def test_non_critical_escalation_is_not_priority():
    hist = {"embeddings": [100.0, 400.0, 700.0]}
    d = medic.decide(unhealthy_keys={"embeddings"}, router_healthy=True,
                     restart_history=hist, now=800.0)
    assert d[0].action == "escalate" and d[0].priority is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_medic.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'soveryn.platform.medic'`

- [ ] **Step 3: Write the decision core**

```python
# soveryn/platform/medic/__init__.py
"""SOVERYN Medic — fleet auto-heal actuator (green actions only)."""
```

```python
# soveryn/platform/medic/medic.py
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
import os
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_medic.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/medic/__init__.py soveryn/platform/medic/medic.py tests/test_medic.py
git commit -m "feat(medic): pure decision core with per-target cooldown, loop-guard, router-collision guard"
```

---

## Task 4: Medic I/O shell — probe, act, escalate, audit

**Files:**
- Modify: `soveryn/platform/medic/medic.py` (append I/O shell + `run_once`)
- Test: `tests/test_medic.py` (append)

**Interfaces:**
- Consumes: `decide`, `TARGETS`, `MedicDecision` from Task 3; `signal_sender.send` from `soveryn.agents.ares.signal_sender`.
- Produces:
  - `probe_unhealthy(*, http_ok, unit_active, heartbeat_age, comfyui_on_her_card) -> tuple[set[str], bool]` — pure classifier returning `(unhealthy_keys, router_healthy)` from injected readings.
  - `run_once(now: float | None = None) -> dict` — the tick: probe → decide → act/escalate → persist history → log.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_medic.py
import json


def test_probe_unhealthy_classifies_from_readings():
    unhealthy, router_healthy = medic.probe_unhealthy(
        http_ok={"vnext": False, "embeddings": True, "router": True},
        unit_active={"dream": False, "x-feed": True, "tg-bridge": True, "parakeet": True,
                     "vett-patrol": True, "representation": True},
        heartbeat_age=100.0,           # fresh
        comfyui_on_her_card=False,
    )
    assert unhealthy == {"vnext", "dream"}
    assert router_healthy is True


def test_probe_flags_stale_heartbeat_and_comfyui_squatter():
    unhealthy, _ = medic.probe_unhealthy(
        http_ok={"vnext": True, "embeddings": True, "router": True},
        unit_active={"dream": True, "x-feed": True, "tg-bridge": True, "parakeet": True,
                     "vett-patrol": True, "representation": True},
        heartbeat_age=3000.0,          # > 2400 → stale
        comfyui_on_her_card=True,
    )
    assert "heartbeat" in unhealthy and "comfyui" in unhealthy


def test_run_once_acts_and_records_history(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "HISTORY_FILE", tmp_path / "restart_history.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    # everything healthy except embeddings
    monkeypatch.setattr(medic, "_probe", lambda: ({"embeddings"}, True))
    calls = []
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: calls.append((unit, verb)))
    monkeypatch.setattr(medic, "_escalate", lambda d: calls.append(("ESCALATE", d.unit)))

    result = medic.run_once(now=1000.0)

    assert ("soveryn-embeddings.service", "restart") in calls
    assert result["actions"][0]["action"] == "act"
    hist = json.loads((tmp_path / "restart_history.json").read_text())
    assert hist["embeddings"] == [1000.0]


def test_run_once_escalates_and_does_not_restart_when_loopguard_tripped(tmp_path, monkeypatch):
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "HISTORY_FILE", tmp_path / "restart_history.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    (tmp_path / "restart_history.json").write_text(json.dumps({"vnext": [100.0, 400.0, 700.0]}))
    monkeypatch.setattr(medic, "_probe", lambda: ({"vnext"}, True))
    calls = []
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: calls.append(("RESTART", unit)))
    monkeypatch.setattr(medic, "_escalate", lambda d: calls.append(("ESCALATE", d.unit)))

    medic.run_once(now=800.0)

    assert ("ESCALATE", "soveryn-vnext.service") in calls
    assert ("RESTART", "soveryn-vnext.service") not in calls


def test_run_once_never_calls_run_unit_on_a_router(tmp_path, monkeypatch):
    # Defense in depth: even if a router key were somehow unhealthy, no router
    # unit can reach _run_unit (there is no router target).
    monkeypatch.setattr(medic, "STATE_DIR", tmp_path)
    monkeypatch.setattr(medic, "HISTORY_FILE", tmp_path / "restart_history.json")
    monkeypatch.setattr(medic, "LOG_FILE", tmp_path / "medic.jsonl")
    monkeypatch.setattr(medic, "_probe", lambda: (set(medic.TARGETS), True))
    restarted = []
    monkeypatch.setattr(medic, "_run_unit", lambda unit, verb: restarted.append(unit))
    monkeypatch.setattr(medic, "_escalate", lambda d: None)
    medic.run_once(now=5000.0)
    assert not (medic.FORBIDDEN_UNITS & set(restarted))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_medic.py -q -k "probe or run_once or router_never"`
Expected: FAIL with `AttributeError: module 'soveryn.platform.medic.medic' has no attribute 'probe_unhealthy'`

- [ ] **Step 3: Write the I/O shell**

Append to `soveryn/platform/medic/medic.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_medic.py -q`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/medic/medic.py tests/test_medic.py
git commit -m "feat(medic): probe/act/escalate/audit shell with fail-safe readers and router guard"
```

---

## Task 5: Medic entrypoint + systemd units + live smoke

**Files:**
- Create: `soveryn/platform/medic/__main__.py`
- Create: `runtime/soveryn-medic.service`, `runtime/soveryn-medic.timer`
- Test: `tests/test_medic.py` (append one smoke test)

**Interfaces:**
- Consumes: `run_once` from Task 4.
- Produces: `python -m soveryn.platform.medic` runs exactly one tick.

- [ ] **Step 1: Write the failing smoke test**

```python
# append to tests/test_medic.py
import importlib
import subprocess as _sp


def test_module_main_runs_one_tick(monkeypatch):
    called = {}
    monkeypatch.setattr(medic, "run_once", lambda: called.setdefault("ran", True) or {"actions": []})
    main_mod = importlib.import_module("soveryn.platform.medic.__main__")
    main_mod.main()
    assert called.get("ran") is True


def test_service_unit_targets_the_module_and_soveryn_python():
    text = open("runtime/soveryn-medic.service").read()
    assert "python -m soveryn.platform.medic" in text
    assert "/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python" in text
    assert "Type=oneshot" in text


def test_timer_unit_ticks_every_60s():
    text = open("runtime/soveryn-medic.timer").read()
    assert "OnUnitActiveSec=60" in text
    assert "Unit=soveryn-medic.service" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_medic.py -q -k "main or unit or timer"`
Expected: FAIL with `ModuleNotFoundError: No module named 'soveryn.platform.medic.__main__'`

- [ ] **Step 3: Write the entrypoint and units**

```python
# soveryn/platform/medic/__main__.py
"""`python -m soveryn.platform.medic` — one medic tick (systemd oneshot)."""
from __future__ import annotations

import json

from soveryn.platform.medic.medic import run_once


def main() -> None:
    print(json.dumps(run_once()))


if __name__ == "__main__":
    main()
```

```ini
# runtime/soveryn-medic.service
[Unit]
Description=SOVERYN Medic — fleet auto-heal actuator (green actions only; never touches routers)
After=soveryn-vnext.service

[Service]
Type=oneshot
WorkingDirectory=/home/jon-deoliveira/soveryn_vnext
Environment=PATH=/home/jon-deoliveira/miniconda3/envs/soveryn/bin:/usr/bin
Environment=SIGNAL_BOT_NUMBER=+19102489392 SIGNAL_USER_NUMBER=+19105813970 SIGNAL_CLI_BIN=/usr/local/bin/signal-cli
ExecStart=/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m soveryn.platform.medic
```

```ini
# runtime/soveryn-medic.timer
[Unit]
Description=SOVERYN Medic tick (every 60s)

[Timer]
OnBootSec=120
OnUnitActiveSec=60
AccuracySec=5
Unit=soveryn-medic.service

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_medic.py tests/test_ares_vitals_lane.py -q`
Expected: PASS (all green)

- [ ] **Step 5: Live one-shot dry check (does NOT enable the timer)**

Run one real tick manually and confirm it reads the live fleet without acting destructively (with everything healthy it should take no action):

```bash
cd /home/jon-deoliveira/soveryn_vnext
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m soveryn.platform.medic
```
Expected: JSON like `{"unhealthy": [], "actions": []}` (the fleet is currently healthy). Confirm `data/medic/medic.jsonl` got one line.

- [ ] **Step 6: Commit (units staged but timer NOT yet enabled)**

```bash
git add soveryn/platform/medic/__main__.py runtime/soveryn-medic.service runtime/soveryn-medic.timer tests/test_medic.py
git commit -m "feat(medic): module entrypoint + systemd oneshot/timer units (install deferred)"
```

- [ ] **Step 7: Install + enable the timer (LIVE — the actuator goes hot)**

This is the only step that puts the medic in charge of the fleet. Do it last, after all tests are green and the manual tick was clean:

```bash
cp runtime/soveryn-medic.service ~/.config/systemd/user/soveryn-medic.service
cp runtime/soveryn-medic.timer ~/.config/systemd/user/soveryn-medic.timer
systemctl --user daemon-reload
systemctl --user enable --now soveryn-medic.timer
systemctl --user list-timers soveryn-medic.timer --no-pager
```
Expected: the timer is listed and scheduled. Tail `data/medic/medic.jsonl` over the next few minutes to confirm clean 60 s ticks with `"actions": []` on a healthy fleet.

---

## Self-Review

**1. Spec coverage:**
- Ares vitals lane (gpu.headroom, gpu.foreign_proc, delegation.stuck) → Tasks 1–2. ✓
- Reuse existing finding/dedup/Signal pipeline (zero-arg collector, `AresFinding`) → Task 2 registration. ✓
- Medic actuator cloned from router_watchdog (pure decide + shell + per-target cooldown + JSONL) → Tasks 3–4. ✓
- Never touches routers (test-asserted) → Task 3 `test_no_target_is_a_router_unit`, Task 4 `test_run_once_never_calls_run_unit_on_a_router`, plus `_run_unit` runtime guard. ✓
- Green actions auto, reds page; EMERGENCY bypasses quiet hours → severities in Tasks 1/3 + reuse of `router.py`/`signal_sender.py` (not re-implemented). ✓
- Set-points (headroom 2/3 GB, Quadro 1 GB, heartbeat 40 min, delegation 360 s, loop-guard 3/900 s, cooldowns) → Global Constraints + Tasks 1/3/4. ✓
- No active TTFT probe → not built. ✓
- **Deferred:** her-card thermal → EMERGENCY bump (documented in Global Constraints; needs Jon's ack). This is the one spec item intentionally not implemented — surface it at handoff.

**2. Placeholder scan:** none — every code step contains full code; every run step has an exact command + expected output.

**3. Type consistency:** `AresFinding(finding_type, severity, evidence, key=)` matches `findings.py`. `collect_vitals_live` is zero-arg (matches `Collector` contract). `decide(...)` signature and `MedicDecision.action` values (`act`/`escalate`/`skip_cooldown`/`skip_router_down`) are identical across Tasks 3–4. `TARGETS` keys used in `probe_unhealthy`/`_probe` (`vnext`, `embeddings`, `heartbeat`, `dream`, `x-feed`, `tg-bridge`, `parakeet`, `vett-patrol`, `representation`, `comfyui`) all exist in the `TARGETS` dict. `verb` field drives `_run_unit`. Consistent.
