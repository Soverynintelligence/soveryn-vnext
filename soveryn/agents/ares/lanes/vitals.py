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
