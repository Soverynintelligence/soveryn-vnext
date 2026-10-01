"""What is actually running on each GPU — the Mission Control "Rig" panel.

`/api/system/gpu` (gpu_stats.py) reports utilization/memory/temp per card but
can't say WHAT occupies it. This joins two nvidia-smi queries:

  1. `--query-gpu=...`         — per-GPU identity + totals.
  2. `--query-compute-apps=...` — which pids occupy which gpu_uuid, and how
     much VRAM each pid holds there.

A pid can legitimately appear on TWO gpu rows (llama.cpp allocates a small
context on a second card for cross-GPU model splits) — both rows are real
and must both survive to the final residents list; we never dedupe by pid.

Pid -> human name resolution reads /proc directly (never a subprocess per
pid), in this fallback order: `--alias <name>` from /proc/<pid>/cmdline,
then the systemd unit from /proc/<pid>/cgroup (soveryn-<x>.service -> <x>),
then /proc/<pid>/comm. A pid that vanished between the two nvidia-smi calls
resolves to None and is dropped, not fatal.

Subprocess-cached for 5 seconds in-process, same as gpu_stats.py. Gracefully
degrades to available=False when nvidia-smi is missing (CI, dev laptops).
"""

from __future__ import annotations
import subprocess
import time
from dataclasses import dataclass, field

_CACHE_TTL_SECONDS = 5.0
_NVIDIA_SMI_TIMEOUT_SECONDS = 4.0
_GPU_FIELDS = "index,name,uuid,memory.used,memory.total,utilization.gpu,temperature.gpu"
_APPS_FIELDS = "pid,used_memory,gpu_uuid"


@dataclass(frozen=True)
class Resident:
    name: str          # "aetheria", "vett-scotty", "f5tts", ...
    mem_mib: int


@dataclass(frozen=True)
class RigGpu:
    index: int
    name: str          # "NVIDIA RTX PRO 5000 Blackwell"
    uuid: str
    mem_used_mib: int
    mem_total_mib: int
    util_pct: int
    temp_c: int
    residents: list[Resident] = field(default_factory=list)   # sorted by mem_mib DESC


@dataclass(frozen=True)
class RigStatsResult:
    available: bool
    gpus: list[RigGpu] = field(default_factory=list)
    message: str = ""
    fetched_at: float = 0.0
    # False whenever the --query-compute-apps probe itself failed (missing
    # binary, timeout, non-zero exit) — NOT when it succeeded and legitimately
    # returned zero rows. residents=[] is ambiguous between "nothing running"
    # and "we couldn't ask"; this field is what breaks that ambiguity for the
    # UI. Must never be conflated with `available`, which only reflects the
    # --query-gpu identity probe.
    residents_known: bool = True


_cache: RigStatsResult | None = None


# --- parsing --------------------------------------------------------------

def _parse_gpu_list(raw: str) -> list[dict]:
    out: list[dict] = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 7:
            continue
        try:
            out.append({
                "index": int(cols[0]),
                "name": cols[1],
                "uuid": cols[2],
                "mem_used_mib": int(float(cols[3])),
                "mem_total_mib": int(float(cols[4])),
                "util_pct": int(float(cols[5])),
                "temp_c": int(float(cols[6])),
            })
        except ValueError:
            # An unparseable numeric field must not become a fake 0 — skip
            # the row instead of misrepresenting state.
            continue
    return out


def _parse_compute_apps(raw: str) -> list[tuple[int, int, str]]:
    """Returns (pid, mem_mib, gpu_uuid) rows. Duplicate pids across gpus are
    kept as-is — deduping would silently drop a real cross-GPU allocation."""
    out: list[tuple[int, int, str]] = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 3:
            continue
        try:
            pid = int(cols[0])
            mem_mib = int(float(cols[1]))
        except ValueError:
            continue
        uuid = cols[2]
        out.append((pid, mem_mib, uuid))
    return out


# --- pid -> name resolution, reading /proc directly ------------------------

def _read_cmdline_alias(pid: int) -> str | None:
    """`--alias <name>` from the NUL-separated /proc/<pid>/cmdline."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
    except OSError:
        return None
    parts = raw.split(b"\x00")
    for i, part in enumerate(parts):
        if part == b"--alias" and i + 1 < len(parts):
            val = parts[i + 1].decode("utf-8", "replace").strip()
            if val:
                return val
    return None


def _read_cgroup_unit(pid: int) -> str | None:
    """The systemd unit from /proc/<pid>/cgroup, e.g. '.../soveryn-f5tts.service'
    -> 'f5tts'. A leading 'soveryn-' is stripped; units without it (e.g.
    'parakeet.service') are returned as-is."""
    try:
        with open(f"/proc/{pid}/cgroup", "r") as f:
            text = f.read()
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line.endswith(".service"):
            continue
        unit = line.rsplit("/", 1)[-1][: -len(".service")]
        if unit.startswith("soveryn-"):
            unit = unit[len("soveryn-"):]
        if unit:
            return unit
    return None


def _read_comm(pid: int) -> str | None:
    """Last-resort fallback: /proc/<pid>/comm."""
    try:
        with open(f"/proc/{pid}/comm", "r") as f:
            name = f.read().strip()
    except OSError:
        return None
    return name or None


def _resolve_pid_name(pid: int) -> str | None:
    """--alias wins, then the cgroup unit, then comm. None means the pid
    vanished (or is otherwise unresolvable) and the row must be dropped."""
    return _read_cmdline_alias(pid) or _read_cgroup_unit(pid) or _read_comm(pid)


def _house_resident_name(name: str, gpu_name: str) -> str:
    """Quadro Qwen 3.8 is still launched as `--alias kernel` (legacy preset).

    Kernel the citizen lives on Spark GLM. Do not pin that name to a Quadro.
    """
    if name.lower() == "kernel" and "quadro" in gpu_name.lower():
        return "qwen38"
    return name


# --- probe + cache ----------------------------------------------------------

def _run_smi(query_flag: str, fields: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["nvidia-smi", f"--{query_flag}={fields}", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
    )


def _probe() -> RigStatsResult:
    try:
        gpu_proc = _run_smi("query-gpu", _GPU_FIELDS)
    except FileNotFoundError:
        return RigStatsResult(available=False, message="nvidia-smi not available", fetched_at=time.time())
    except subprocess.TimeoutExpired:
        return RigStatsResult(available=False, message="nvidia-smi timed out", fetched_at=time.time())

    if gpu_proc.returncode != 0:
        return RigStatsResult(
            available=False,
            message=f"nvidia-smi exit {gpu_proc.returncode}: {gpu_proc.stderr.strip() or 'no stderr'}",
            fetched_at=time.time(),
        )

    try:
        apps_proc = _run_smi("query-compute-apps", _APPS_FIELDS)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        apps_proc = None

    # residents_known is False for ANY failure of the compute-apps probe —
    # missing binary, timeout, or non-zero exit. Only a genuine rc==0 counts
    # as "we asked and got an answer" (even if that answer is zero rows).
    residents_known = apps_proc is not None and apps_proc.returncode == 0
    apps_raw = apps_proc.stdout if residents_known else ""

    gpu_rows = _parse_gpu_list(gpu_proc.stdout)
    app_rows = _parse_compute_apps(apps_raw)

    gpu_name_by_uuid = {row["uuid"]: row["name"] for row in gpu_rows}
    residents_by_uuid: dict[str, list[Resident]] = {row["uuid"]: [] for row in gpu_rows}
    for pid, mem_mib, uuid in app_rows:
        if uuid not in residents_by_uuid:
            continue  # compute-app row for a gpu_uuid we don't have identity for
        name = _resolve_pid_name(pid)
        if name is None:
            continue  # pid vanished between the two nvidia-smi calls — skip, don't crash
        name = _house_resident_name(name, gpu_name_by_uuid.get(uuid, ""))
        residents_by_uuid[uuid].append(Resident(name=name, mem_mib=mem_mib))

    gpus = [
        RigGpu(
            index=row["index"], name=row["name"], uuid=row["uuid"],
            mem_used_mib=row["mem_used_mib"], mem_total_mib=row["mem_total_mib"],
            util_pct=row["util_pct"], temp_c=row["temp_c"],
            residents=sorted(residents_by_uuid[row["uuid"]], key=lambda r: r.mem_mib, reverse=True),
        )
        for row in gpu_rows
    ]

    return RigStatsResult(
        available=True, gpus=gpus, fetched_at=time.time(), residents_known=residents_known,
    )


def get_rig_stats(*, _force_refresh: bool = False) -> RigStatsResult:
    """Return current per-GPU residency stats, cached for 5 seconds."""
    global _cache
    now = time.time()
    if not _force_refresh and _cache is not None and (now - _cache.fetched_at) < _CACHE_TTL_SECONDS:
        return _cache
    _cache = _probe()
    return _cache
