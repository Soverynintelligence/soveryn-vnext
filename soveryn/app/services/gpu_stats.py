"""Wrap `nvidia-smi --query-gpu` for the command center system panel.

Subprocess-cached for 5 seconds in-process to avoid hammering the GPU on
every page poll. Gracefully degrades when nvidia-smi is missing (CI, dev
laptops without CUDA).
"""

from __future__ import annotations
import subprocess
import time
from dataclasses import dataclass, field

_CACHE_TTL_SECONDS = 5.0
_NVIDIA_SMI_TIMEOUT_SECONDS = 4.0
_QUERY_FIELDS = "index,utilization.gpu,temperature.gpu,memory.used,memory.total"


@dataclass(frozen=True)
class GpuStat:
    index: int
    util_pct: int
    temp_c: int
    mem_used_mib: float
    mem_total_mib: int


@dataclass(frozen=True)
class GpuStatsResult:
    available: bool
    gpus: list[GpuStat] = field(default_factory=list)
    message: str = ""
    fetched_at: float = 0.0


_cache: GpuStatsResult | None = None


def _parse_nvidia_smi(raw: str) -> list[GpuStat]:
    out: list[GpuStat] = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 5:
            continue
        try:
            out.append(GpuStat(
                index=int(cols[0]),
                util_pct=int(float(cols[1])),
                temp_c=int(float(cols[2])),
                mem_used_mib=float(cols[3]),
                mem_total_mib=int(float(cols[4])),
            ))
        except ValueError:
            continue
    return out


def _run_nvidia_smi() -> GpuStatsResult:
    try:
        proc = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_QUERY_FIELDS}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return GpuStatsResult(available=False, message="nvidia-smi not available", fetched_at=time.time())
    except subprocess.TimeoutExpired:
        return GpuStatsResult(available=False, message="nvidia-smi timed out", fetched_at=time.time())

    if proc.returncode != 0:
        return GpuStatsResult(
            available=False,
            message=f"nvidia-smi exit {proc.returncode}: {proc.stderr.strip() or 'no stderr'}",
            fetched_at=time.time(),
        )
    return GpuStatsResult(
        available=True,
        gpus=_parse_nvidia_smi(proc.stdout),
        fetched_at=time.time(),
    )


def get_gpu_stats(*, _force_refresh: bool = False) -> GpuStatsResult:
    """Return current GPU stats, cached for 5 seconds."""
    global _cache
    now = time.time()
    if not _force_refresh and _cache is not None and (now - _cache.fetched_at) < _CACHE_TTL_SECONDS:
        return _cache
    _cache = _run_nvidia_smi()
    return _cache
