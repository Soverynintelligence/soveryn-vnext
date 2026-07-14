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
import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field

SPARK_SSH_USER = "soverynspark"
SPARK_FABRIC_HOST = "10.10.10.2"
SPARK_WIFI_HOST = "192.168.86.26"
SPARK_VLLM_PORT = 8000

# Worst case: _SSH_TIMEOUT_SECONDS * 2 hosts + _HTTP_TIMEOUT_SECONDS * 2 calls
# (models + metrics) = 4*2 + 3*2 = 14s, comfortably inside the cache TTL so a
# hanging (not dead) Spark can't cause overlapping probes the cache can't
# suppress. A normal probe takes well under 1s.
_CACHE_TTL_SECONDS = 20.0
_SSH_TIMEOUT_SECONDS = 4.0
_SSH_CONNECT_TIMEOUT = 2
_HTTP_TIMEOUT_SECONDS = 3.0

_SECTION = "---"

# One SSH round-trip for everything the box can tell us. The shell reports the
# LAST command's exit status, and ssh propagates it as proc.returncode — so
# the docker command must never itself fail, or a Docker daemon hiccup would
# be mistaken for "host unreachable" and discard perfectly good GPU/mem data.
# `-a` (not just running) so a crashed/exited container is visible too.
PROBE_CMD = (
    "nvidia-smi --query-gpu=utilization.gpu,temperature.gpu "
    "--format=csv,noheader,nounits 2>/dev/null | head -1; "
    f"echo {_SECTION}; "
    "free -b | sed -n 2p; "
    f"echo {_SECTION}; "
    "docker ps -a --format '{{.Names}}|{{.State}}' || true"
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


_cache: SparkStatsResult | None = None


def _ssh(host: str) -> subprocess.CompletedProcess | None:
    """One SSH round-trip. Returns None if ssh itself is missing or hangs."""
    try:
        return subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={_SSH_CONNECT_TIMEOUT}",
                "-o", "StrictHostKeyChecking=accept-new",
                f"{SPARK_SSH_USER}@{host}",
                PROBE_CMD,
            ],
            capture_output=True, text=True, timeout=_SSH_TIMEOUT_SECONDS,
        )
    except Exception:
        # Anything from the subprocess call — missing/unexecutable ssh binary,
        # a hung connection, or a non-UTF8 byte in remote output tripping
        # text=True decoding — must degrade to "unreachable", never raise.
        return None


def _http_json(url: str) -> dict | list | None:
    try:
        with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT_SECONDS) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _http_text(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=_HTTP_TIMEOUT_SECONDS) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


def _fetch_vllm(host: str) -> SparkVllm:
    """A dead vLLM must not hide a live box — degrade to up=False, never raise."""
    base = f"http://{host}:{SPARK_VLLM_PORT}"
    models = _http_json(f"{base}/v1/models")
    if not models:
        return SparkVllm(up=False)
    try:
        model = models["data"][0]["id"]
    except (KeyError, IndexError, TypeError):
        model = None

    m = _parse_prometheus(_http_text(f"{base}/metrics") or "")
    return SparkVllm(
        up=True,
        model=model,
        requests_running=m.get("vllm:num_requests_running"),
        requests_waiting=m.get("vllm:num_requests_waiting"),
        kv_cache_pct=m.get("vllm:kv_cache_usage_perc"),
    )


def _probe() -> SparkStatsResult:
    # Fabric FIRST. The fallback order is the link health check.
    last_stderr = ""
    for path, host in (("fabric", SPARK_FABRIC_HOST), ("wifi", SPARK_WIFI_HOST)):
        proc = _ssh(host)
        if proc is None or proc.returncode != 0:
            if proc is not None and proc.stderr and proc.stderr.strip():
                last_stderr = proc.stderr.strip()
            continue
        spark_host, containers = _parse_probe(proc.stdout)
        return SparkStatsResult(
            available=True,
            path=path,
            host=spark_host,
            containers=containers,
            vllm=_fetch_vllm(host),
            fetched_at=time.time(),
        )
    message = f"Spark unreachable over fabric ({SPARK_FABRIC_HOST}) or WiFi ({SPARK_WIFI_HOST})"
    if last_stderr:
        message += f": {last_stderr}"
    return SparkStatsResult(
        available=False,
        message=message,
        fetched_at=time.time(),
    )


def get_spark_stats(*, _force_refresh: bool = False) -> SparkStatsResult:
    """Current Spark stats, cached for 20s (SSH spawn is ~200ms)."""
    global _cache
    now = time.time()
    if not _force_refresh and _cache is not None and (now - _cache.fetched_at) < _CACHE_TTL_SECONDS:
        return _cache
    _cache = _probe()
    return _cache
