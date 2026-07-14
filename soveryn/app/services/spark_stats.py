"""Probe the DGX Spark for the Mission Control tile.

The Spark is reachable two ways: the ConnectX-7 direct fabric (10.10.10.2, ~118
Gbit/s) and WiFi (192.168.86.26, orders of magnitude slower). If the fabric drops,
everything keeps working over WiFi with nothing to announce it. So we probe the
fabric FIRST and fall back to WiFi — and we report which path answered. The
fallback IS the link health check.

Unified memory: on GB10, `nvidia-smi` reports memory.total as [N/A] because memory
is unified with the host. Memory therefore comes from `free -b`, never nvidia-smi.
"""

from __future__ import annotations
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

SPARK_SSH_USER = "soverynspark"
SPARK_FABRIC_HOST = "10.10.10.2"
SPARK_WIFI_HOST = "192.168.86.26"
SPARK_VLLM_PORT = 8000

_CACHE_TTL_SECONDS = 10.0
_SSH_TIMEOUT_SECONDS = 8.0
_SSH_CONNECT_TIMEOUT = 2
_HTTP_TIMEOUT_SECONDS = 3.0

_SECTION = "---"

# One SSH round-trip for everything the box can tell us.
PROBE_CMD = (
    "nvidia-smi --query-gpu=utilization.gpu,temperature.gpu "
    "--format=csv,noheader,nounits 2>/dev/null | head -1; "
    f"echo {_SECTION}; "
    "free -b | sed -n 2p; "
    f"echo {_SECTION}; "
    "docker ps --format '{{.Names}}|{{.State}}'"
)


@dataclass(frozen=True)
class SparkHost:
    gpu_util_pct: int | None = None
    gpu_temp_c: int | None = None
    mem_used_bytes: int | None = None
    mem_total_bytes: int | None = None


@dataclass(frozen=True)
class SparkContainer:
    name: str
    state: str


@dataclass(frozen=True)
class SparkVllm:
    up: bool = False
    model: str | None = None
    requests_running: float | None = None
    requests_waiting: float | None = None
    kv_cache_pct: float | None = None


@dataclass(frozen=True)
class SparkStatsResult:
    available: bool
    path: str | None = None           # "fabric" | "wifi" | None
    message: str = ""
    host: SparkHost | None = None
    containers: list[SparkContainer] = field(default_factory=list)
    vllm: SparkVllm | None = None
    fetched_at: float = 0.0


def _int_or_none(text: str) -> int | None:
    """GB10 emits '[N/A]' for unsupported fields. Never fake a number."""
    text = text.strip()
    if not text or text.upper().startswith("[N/A"):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_probe(raw: str) -> tuple[SparkHost, list[SparkContainer]]:
    parts = raw.split(_SECTION)
    gpu_raw = parts[0] if len(parts) > 0 else ""
    mem_raw = parts[1] if len(parts) > 1 else ""
    dock_raw = parts[2] if len(parts) > 2 else ""

    util = temp = None
    gpu_line = gpu_raw.strip().splitlines()
    if gpu_line:
        cols = [c.strip() for c in gpu_line[0].split(",")]
        if len(cols) >= 2:
            util, temp = _int_or_none(cols[0]), _int_or_none(cols[1])

    mem_used = mem_total = None
    mem_line = mem_raw.strip().splitlines()
    if mem_line:
        cols = mem_line[0].split()
        # free -b: Mem: <total> <used> <free> <shared> <buff/cache> <available>
        if len(cols) >= 3:
            mem_total, mem_used = _int_or_none(cols[1]), _int_or_none(cols[2])

    containers = []
    for line in dock_raw.strip().splitlines():
        if "|" not in line:
            continue
        name, _, state = line.partition("|")
        containers.append(SparkContainer(name=name.strip(), state=state.strip()))

    return SparkHost(gpu_util_pct=util, gpu_temp_c=temp,
                     mem_used_bytes=mem_used, mem_total_bytes=mem_total), containers


def _parse_prometheus(raw: str) -> dict[str, float]:
    """Flatten `name{labels} value` lines to {name: value}. Comments ignored."""
    out: dict[str, float] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, rest = line.partition("{")
        if rest:
            _, _, value = rest.partition("}")
        else:
            name, _, value = line.partition(" ")
        try:
            out[name.strip()] = float(value.strip())
        except ValueError:
            continue
    return out
