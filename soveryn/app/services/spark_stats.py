"""Probe the DGX Spark for the Mission Control tile.

The Spark is reachable two ways: the ConnectX-7 direct fabric (10.10.10.2, ~118
Gbit/s) and WiFi (192.168.86.26, orders of magnitude slower). If the fabric drops,
everything keeps working over WiFi with nothing to announce it. So we probe the
fabric FIRST and fall back to WiFi — and we report which path answered. The
fallback IS the link health check.

Reachability and path are decided over HTTP to vLLM, NOT SSH. A wedged sshd
(e.g. under memory pressure — TCP/22 accepts but never sends a banner) is a
real production failure mode, and the box can be completely healthy and still
serving inference the entire time. SSH is only used as OPTIONAL ENRICHMENT —
host metrics (GPU util/temp, unified memory, container list) — run against
whichever host answered over HTTP. If SSH fails, the result still reports
available=True with the vLLM data; only the host section degrades
(`host_known=False`, host=None, containers=[]). Only when BOTH HTTP and SSH
fail on BOTH hosts is the Spark genuinely unreachable.

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
# Hard brain (Lightning / Qwen switch) is qwen-serve on :8001.
# Laguna on :8000 was retired 2026-08-12; keep as fallback if someone
# brings it back. CC was still probing 8000 → false "vllm down".
SPARK_VLLM_PORT = 8001
SPARK_VLLM_PORTS = (8001, 8000)

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
    # SSH is enrichment, not reachability — a wedged sshd (e.g. under memory
    # pressure) must never make a box that is genuinely serving traffic render
    # dead. False means the SSH probe failed: host is None and containers is
    # []. This is the same distinction rig_stats.py makes with
    # `residents_known` — "unknown" must never be rendered as either healthy
    # or down.
    host_known: bool = True


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
    """A dead vLLM must not hide a live box — degrade to up=False, never raise.

    Probes SPARK_VLLM_PORTS in order (:8001 hard brain, then :8000 legacy).
    """
    for port in SPARK_VLLM_PORTS:
        base = f"http://{host}:{port}"
        models = _http_json(f"{base}/v1/models")
        if not models:
            continue
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
    return SparkVllm(up=False)


def _probe() -> SparkStatsResult:
    # Step 1 — reachability AND path, decided over HTTP to vLLM. Fabric tried
    # first: the fabric/wifi order IS the link health check, same as before,
    # just moved off of SSH and onto the channel that actually matters.
    last_stderr = ""
    http_path: str | None = None
    http_host: str | None = None
    vllm: SparkVllm | None = None
    for cand_path, cand_host in (("fabric", SPARK_FABRIC_HOST), ("wifi", SPARK_WIFI_HOST)):
        v = _fetch_vllm(cand_host)
        if v.up:
            http_path, http_host, vllm = cand_path, cand_host, v
            break

    # Step 2 — SSH is optional enrichment for host metrics only, run against
    # whichever host answered over HTTP. If HTTP found nothing at all, SSH
    # becomes the last-resort reachability check itself (fabric first) so a
    # box with a wedged/absent vLLM but a live sshd still reports available.
    ssh_targets = (
        [(http_path, http_host)] if http_host is not None
        else [("fabric", SPARK_FABRIC_HOST), ("wifi", SPARK_WIFI_HOST)]
    )

    path = http_path
    spark_host: SparkHost | None = None
    containers: list[SparkContainer] = []
    host_known = False

    for cand_path, cand_host in ssh_targets:
        proc = _ssh(cand_host)
        if proc is None or proc.returncode != 0:
            if proc is not None and proc.stderr and proc.stderr.strip():
                last_stderr = proc.stderr.strip()
            continue
        spark_host, containers = _parse_probe(proc.stdout)
        host_known = True
        if path is None:
            # HTTP was silent everywhere; SSH is now the source of both
            # reachability and path.
            path = cand_path
            vllm = _fetch_vllm(cand_host)
        break

    if path is None:
        message = f"Spark unreachable over fabric ({SPARK_FABRIC_HOST}) or WiFi ({SPARK_WIFI_HOST})"
        if last_stderr:
            message += f": {last_stderr}"
        return SparkStatsResult(
            available=False,
            host_known=False,
            message=message,
            fetched_at=time.time(),
        )

    # The box is reachable (HTTP and/or SSH answered). Degrade the host
    # section, never the whole result, when SSH couldn't get host metrics —
    # but still surface why, since that stderr is exactly what let us
    # diagnose tonight's "healthy box painted dead" incident.
    message = f"host metrics unavailable: {last_stderr}" if (not host_known and last_stderr) else ""

    return SparkStatsResult(
        available=True,
        path=path,
        message=message,
        host=spark_host if host_known else None,
        containers=containers if host_known else [],
        vllm=vllm,
        host_known=host_known,
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
