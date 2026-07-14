# Mission Control DGX Spark Tile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DGX Spark tile to Mission Control showing box health, vLLM serving state, and — critically — whether the Spark is reached over the 200G fabric or has silently fallen back to WiFi.

**Architecture:** A new `spark_stats.py` service SSHes to the Spark (fabric address first, WiFi second) for host + container state, and scrapes vLLM's Prometheus endpoint for serving state. The fabric-then-WiFi fallback order *is* the link health check — whichever path answers is what the tile reports. A new `/api/system/spark` route exposes it; a tile in `command_center.html` renders it green (fabric) / amber (WiFi = degraded) / red (down).

**Tech Stack:** Python 3.11 (conda env `soveryn`), Flask blueprints, stdlib `subprocess` + `urllib.request` (no new dependencies), vanilla JS in a Jinja template, pytest with `unittest.mock.patch`.

## Global Constraints

- **Run tests with the soveryn conda env python, NOT base 3.13:** `~/miniconda3/envs/soveryn/bin/python -m pytest ...`
- **No new dependencies.** Use stdlib `subprocess` and `urllib.request`. The codebase's existing `gpu_stats.py` uses `subprocess` only; tests patch `subprocess.run`.
- **Spark connection facts (verified 2026-07-13/14):** SSH user `soverynspark`; fabric `10.10.10.2`; WiFi `192.168.86.26`; vLLM on port `8000`; key auth from the tower already works on both addresses.
- **Unified memory:** on GB10, `nvidia-smi` reports `memory.total = [N/A]`. Memory MUST come from `free -b`. Any field that comes back `[N/A]` must degrade to `None`, never to a garbage number.
- **vLLM metric names verified against the live Spark (vLLM 0.25.0):** `vllm:num_requests_running`, `vllm:num_requests_waiting`, `vllm:kv_cache_usage_perc`.
- **Read-only.** No route may start/stop/mutate anything on the Spark.
- Blueprints register in `soveryn/app/startup.py` (~line 1212). `api_system` is already registered — Task 2 adds a route to the existing blueprint, so no new registration is needed.

---

## File Structure

| File | Responsibility |
|---|---|
| `soveryn/app/services/spark_stats.py` (create) | Probe the Spark. Owns SSH, HTTP, parsing, caching, degradation. Knows nothing about Flask. |
| `tests/test_services_spark_stats.py` (create) | Unit tests for the probe + parsers. |
| `soveryn/app/routes/api_system.py` (modify) | Add `GET /api/system/spark`. Pure serialization — no logic. |
| `tests/test_app_api_spark_route.py` (create) | Route-level tests. |
| `soveryn/app/templates/command_center.html` (modify) | The tile + its fetch/render function. |

---

### Task 1: `spark_stats.py` — parsers

**Files:**
- Create: `soveryn/app/services/spark_stats.py`
- Test: `tests/test_services_spark_stats.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SparkHost`, `SparkContainer`, `SparkVllm`, `SparkStatsResult` dataclasses; `_parse_probe(raw: str) -> tuple[SparkHost, list[SparkContainer]]`; `_parse_prometheus(raw: str) -> dict[str, float]`. Task 2 consumes `SparkStatsResult`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_services_spark_stats.py
"""Tests for soveryn/app/services/spark_stats.py."""

from soveryn.app.services.spark_stats import (
    _parse_probe, _parse_prometheus, SparkContainer,
)

PROBE_OK = """45, 52
---
Mem:  129922760704 52613349376 17179869184 0 60129542144 74000000000
---
nemotron-spark|running
compare|running
"""

# GB10 reports [N/A] for anything memory-related, and may for util/temp too.
PROBE_NA = """[N/A], [N/A]
---
Mem:  129922760704 52613349376 17179869184 0 60129542144 74000000000
---
nemotron-spark|running
"""


def test_parse_probe_reads_gpu_and_unified_memory():
    host, containers = _parse_probe(PROBE_OK)
    assert host.gpu_util_pct == 45
    assert host.gpu_temp_c == 52
    # memory comes from `free -b`, NOT nvidia-smi
    assert host.mem_total_bytes == 129922760704
    assert host.mem_used_bytes == 52613349376
    assert containers == [
        SparkContainer(name="nemotron-spark", state="running"),
        SparkContainer(name="compare", state="running"),
    ]


def test_parse_probe_na_gpu_fields_degrade_to_none_not_garbage():
    """GB10's nvidia-smi returns [N/A]. That must become None, never 0 or a crash."""
    host, containers = _parse_probe(PROBE_NA)
    assert host.gpu_util_pct is None
    assert host.gpu_temp_c is None
    # memory still works, because it comes from free(1)
    assert host.mem_total_bytes == 129922760704
    assert len(containers) == 1


def test_parse_probe_empty_does_not_raise():
    host, containers = _parse_probe("")
    assert host.gpu_util_pct is None
    assert host.mem_total_bytes is None
    assert containers == []


def test_parse_prometheus_extracts_vllm_gauges():
    raw = (
        '# TYPE vllm:num_requests_running gauge\n'
        'vllm:num_requests_running{engine="0",model_name="nemotron"} 3.0\n'
        'vllm:num_requests_waiting{engine="0",model_name="nemotron"} 1.0\n'
        'vllm:kv_cache_usage_perc{engine="0",model_name="nemotron"} 0.42\n'
    )
    m = _parse_prometheus(raw)
    assert m["vllm:num_requests_running"] == 3.0
    assert m["vllm:num_requests_waiting"] == 1.0
    assert m["vllm:kv_cache_usage_perc"] == 0.42


def test_parse_prometheus_ignores_comments_and_junk():
    assert _parse_prometheus("# TYPE foo gauge\n\ngarbage line\n") == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_services_spark_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soveryn.app.services.spark_stats'`

- [ ] **Step 3: Write the module (dataclasses + parsers only)**

```python
# soveryn/app/services/spark_stats.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_services_spark_stats.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/services/spark_stats.py tests/test_services_spark_stats.py
git commit -m "feat(spark): parsers for the Spark probe — unified memory from free(1), [N/A] degrades to None"
```

---

### Task 2: `spark_stats.py` — probe, fabric/WiFi fallback, cache

**Files:**
- Modify: `soveryn/app/services/spark_stats.py` (append)
- Test: `tests/test_services_spark_stats.py` (append)

**Interfaces:**
- Consumes: `_parse_probe`, `_parse_prometheus`, the dataclasses from Task 1.
- Produces: `get_spark_stats(*, _force_refresh: bool = False) -> SparkStatsResult` and the module-level `_cache`. Task 3's route calls `get_spark_stats()` and resets `_cache` in tests.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_services_spark_stats.py
import subprocess
from unittest.mock import patch

from soveryn.app.services import spark_stats
from soveryn.app.services.spark_stats import get_spark_stats


def _ssh_ok(stdout=PROBE_OK):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _ssh_fail():
    return subprocess.CompletedProcess(args=[], returncode=255, stdout="",
                                       stderr="ssh: connect ... No route to host")


METRICS = (
    'vllm:num_requests_running{model_name="nemotron"} 2.0\n'
    'vllm:num_requests_waiting{model_name="nemotron"} 0.0\n'
    'vllm:kv_cache_usage_perc{model_name="nemotron"} 0.25\n'
)


def _fake_http(url, timeout=0):
    """Stand-in for urllib.request.urlopen — supports `with ... as r: r.read()`."""
    class _R:
        def __enter__(self_inner):
            return self_inner
        def __exit__(self_inner, *a):
            return False
        def read(self_inner):
            if "/v1/models" in url:
                return b'{"data":[{"id":"nemotron"}]}'
            return METRICS.encode()
    return _R()


def test_fabric_path_is_preferred_and_reported():
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_ok()) as run, \
         patch("urllib.request.urlopen", side_effect=_fake_http):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is True
    assert r.path == "fabric"
    # the fabric address must be the one it tried first
    assert spark_stats.SPARK_FABRIC_HOST in " ".join(run.call_args_list[0][0][0])
    assert r.host.gpu_util_pct == 45
    assert r.vllm.up is True
    assert r.vllm.model == "nemotron"
    assert r.vllm.kv_cache_pct == 0.25


def test_wifi_fallback_is_reported_as_degraded():
    """THE POINT OF THIS FEATURE. Fabric down + WiFi up must NOT look healthy."""
    spark_stats._cache = None
    with patch("subprocess.run", side_effect=[_ssh_fail(), _ssh_ok()]), \
         patch("urllib.request.urlopen", side_effect=_fake_http):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is True
    assert r.path == "wifi"          # <-- amber in the UI, not green


def test_both_paths_down_degrades_cleanly():
    spark_stats._cache = None
    with patch("subprocess.run", side_effect=[_ssh_fail(), _ssh_fail()]):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is False
    assert r.path is None
    assert r.host is None
    assert r.containers == []
    assert r.message


def test_box_up_but_vllm_dead_still_reports_the_box():
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_ok()), \
         patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        r = get_spark_stats(_force_refresh=True)
    assert r.available is True
    assert r.host.gpu_util_pct == 45
    assert r.vllm.up is False


def test_caches_within_window():
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_ok()) as run, \
         patch("urllib.request.urlopen", side_effect=_fake_http):
        get_spark_stats(_force_refresh=True)
        get_spark_stats()
        get_spark_stats()
    assert run.call_count == 1
```

Add `import urllib.error` to the test file's imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_services_spark_stats.py -v -k "fabric or wifi or down or vllm_dead or caches"`
Expected: FAIL — `AttributeError: module ... has no attribute 'get_spark_stats'`

- [ ] **Step 3: Append the implementation**

```python
# append to soveryn/app/services/spark_stats.py
import json

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
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _http_json(url: str) -> dict | None:
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
    for path, host in (("fabric", SPARK_FABRIC_HOST), ("wifi", SPARK_WIFI_HOST)):
        proc = _ssh(host)
        if proc is None or proc.returncode != 0:
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
    return SparkStatsResult(
        available=False,
        message="Spark unreachable over fabric (10.10.10.2) or WiFi (192.168.86.26)",
        fetched_at=time.time(),
    )


def get_spark_stats(*, _force_refresh: bool = False) -> SparkStatsResult:
    """Current Spark stats, cached for 10s (SSH spawn is ~200ms)."""
    global _cache
    now = time.time()
    if not _force_refresh and _cache is not None and (now - _cache.fetched_at) < _CACHE_TTL_SECONDS:
        return _cache
    _cache = _probe()
    return _cache
```

- [ ] **Step 4: Run the full service test file**

Run: `~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_services_spark_stats.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/services/spark_stats.py tests/test_services_spark_stats.py
git commit -m "feat(spark): probe with fabric-then-WiFi fallback — the fallback IS the link health check"
```

---

### Task 3: `GET /api/system/spark`

**Files:**
- Modify: `soveryn/app/routes/api_system.py`
- Test: `tests/test_app_api_spark_route.py` (create)

**Interfaces:**
- Consumes: `get_spark_stats()` and `SparkStatsResult` from Task 2.
- Produces: `GET /api/system/spark` returning the JSON the Task 4 tile consumes. Keys: `available`, `path`, `message`, `host`, `containers`, `vllm`, `fetched_at`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_api_spark_route.py
"""Tests for /api/system/spark route."""

import subprocess
from unittest.mock import patch
import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})


@pytest.fixture
def client(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()


PROBE_OK = """45, 52
---
Mem:  129922760704 52613349376 17179869184 0 60129542144 74000000000
---
nemotron-spark|running
"""


def _ssh_ok():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=PROBE_OK, stderr="")


def _ssh_fail():
    return subprocess.CompletedProcess(args=[], returncode=255, stdout="", stderr="no route")


def test_spark_route_returns_json_on_fabric(client):
    from soveryn.app.services import spark_stats
    spark_stats._cache = None
    with patch("subprocess.run", return_value=_ssh_ok()), \
         patch("soveryn.app.services.spark_stats._fetch_vllm",
               return_value=spark_stats.SparkVllm(up=True, model="nemotron",
                                                  requests_running=0.0,
                                                  requests_waiting=0.0,
                                                  kv_cache_pct=0.1)):
        resp = client.get("/api/system/spark")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is True
    assert data["path"] == "fabric"
    assert data["host"]["mem_total_bytes"] == 129922760704
    assert data["containers"][0]["name"] == "nemotron-spark"
    assert data["vllm"]["model"] == "nemotron"


def test_spark_route_when_unreachable(client):
    from soveryn.app.services import spark_stats
    spark_stats._cache = None
    with patch("subprocess.run", side_effect=[_ssh_fail(), _ssh_fail()]):
        resp = client.get("/api/system/spark")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["available"] is False
    assert data["path"] is None
    assert data["host"] is None
    assert data["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_app_api_spark_route.py -v`
Expected: FAIL — 404, because `/api/system/spark` does not exist yet.

- [ ] **Step 3: Add the route**

In `soveryn/app/routes/api_system.py`, extend the existing import line and add the route below `api_system_gpu`:

```python
from soveryn.app.services.gpu_stats import get_gpu_stats
from soveryn.app.services.spark_stats import get_spark_stats
```

```python
@bp.get("/api/system/spark")
def api_system_spark():
    """DGX Spark: box health + vLLM serving state.

    `path` is "fabric" | "wifi" | null. WiFi means the 200G link is DOWN and we
    silently fell back to a ~100x slower path — the UI renders that amber, not green.
    """
    r = get_spark_stats()
    return jsonify({
        "available": r.available,
        "path": r.path,
        "message": r.message,
        "host": asdict(r.host) if r.host else None,
        "containers": [asdict(c) for c in r.containers],
        "vllm": asdict(r.vllm) if r.vllm else None,
        "fetched_at": r.fetched_at,
    }), 200
```

(`asdict` and `jsonify` are already imported in this file.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_app_api_spark_route.py tests/test_app_api_system_routes.py -v`
Expected: PASS (4 passed — the 2 new plus the 2 existing GPU route tests still green)

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/routes/api_system.py tests/test_app_api_spark_route.py
git commit -m "feat(spark): GET /api/system/spark"
```

---

### Task 4: Mission Control tile

**Files:**
- Modify: `soveryn/app/templates/command_center.html`

**Interfaces:**
- Consumes: `GET /api/system/spark` from Task 3.
- Produces: nothing consumed downstream.

- [ ] **Step 1: Add the tile styles**

Insert after the `.gpu-bar .fill` rule (~line 374):

```css
  .spark-tile { font-size:11px; color:rgba(236,243,244,0.7); }
  .spark-tile .link { display:inline-block; padding:2px 7px; border-radius:3px;
    font-weight:600; letter-spacing:0.04em; font-size:10px; margin-bottom:8px; }
  .spark-tile .link.fabric { background:rgba(61,186,111,0.15); color:#3dba6f; }
  .spark-tile .link.wifi   { background:rgba(212,168,39,0.18); color:#d4a827; }
  .spark-tile .link.down   { background:rgba(192,57,43,0.18); color:#c0392b; }
  .spark-tile .row { display:flex; justify-content:space-between; margin-bottom:4px; }
  .spark-tile .row .val { font-variant-numeric:tabular-nums; color:rgba(236,243,244,0.95); }
```

- [ ] **Step 2: Add the tile markup**

Immediately after the closing `</div>` of the `gpu-bars` block (~line 991, inside the same `System` panel):

```html
        <h3 style="margin-top:18px">Spark</h3>
        <div class="spark-tile" data-testid="spark-tile" aria-live="polite" aria-label="DGX Spark status">
          <div style="opacity:0.5">Spark loading…</div>
        </div>
```

- [ ] **Step 3: Add the fetch/render function**

Beside the existing GPU refresh function (near line 1157):

```javascript
  async function refreshSpark() {
    const el = document.querySelector('[data-testid="spark-tile"]');
    if (!el) return;
    const d = await fetchJson("/api/system/spark");

    if (!d || !d.available) {
      el.innerHTML = `<span class="link down">UNREACHABLE</span>
        <div style="opacity:0.6">${(d && d.message) || "Spark unavailable"}</div>`;
      return;
    }

    // WiFi means the 200G fabric is DOWN and we silently fell back to a ~100x
    // slower path. Amber, never green — a green tile here would hide the failure.
    const onFabric = d.path === "fabric";
    const badge = onFabric
      ? `<span class="link fabric">FABRIC · 200G</span>`
      : `<span class="link wifi">DEGRADED — ON WIFI</span>`;

    const h = d.host || {};
    const memPct = (h.mem_total_bytes && h.mem_used_bytes)
      ? Math.round(100 * h.mem_used_bytes / h.mem_total_bytes) : null;
    const gib = b => (b / 1073741824).toFixed(0);
    const v = d.vllm || {};
    const dash = "—";

    el.innerHTML = `
      ${badge}
      <div class="row"><span>gpu</span><span class="val">${
        h.gpu_util_pct == null ? dash : h.gpu_util_pct + "%"} · ${
        h.gpu_temp_c == null ? dash : h.gpu_temp_c + "°C"}</span></div>
      <div class="row"><span>unified mem</span><span class="val">${
        memPct == null ? dash
          : `${gib(h.mem_used_bytes)}/${gib(h.mem_total_bytes)} GiB · ${memPct}%`}</span></div>
      <div class="row"><span>vllm</span><span class="val">${
        v.up ? (v.model || "up") : "down"}</span></div>
      <div class="row"><span>requests</span><span class="val">${
        v.up ? `${v.requests_running ?? 0} run · ${v.requests_waiting ?? 0} wait` : dash}</span></div>
      <div class="row"><span>kv cache</span><span class="val">${
        (v.up && v.kv_cache_pct != null) ? (v.kv_cache_pct * 100).toFixed(1) + "%" : dash}</span></div>
      <div class="row"><span>containers</span><span class="val">${
        (d.containers || []).filter(c => c.state === "running").length} running</span></div>
    `;
  }
```

- [ ] **Step 4: Wire it into the existing poll loop**

Find where `refreshDaemons()` / the GPU refresh are called on an interval (in the `System stats` section, ~line 1201) and add `refreshSpark()` alongside them, matching the existing call/interval style exactly.

- [ ] **Step 5: Verify in the real app**

The Spark is live right now, so this is a real end-to-end check, not a mock.

```bash
systemctl --user restart soveryn-vnext.service
sleep 8
curl -s http://127.0.0.1:5001/api/system/spark | ~/miniconda3/envs/soveryn/bin/python -m json.tool
```

Expected: `"available": true`, `"path": "fabric"`, `"vllm": {"up": true, "model": "nemotron", ...}`.

Then open Mission Control in the browser and confirm the tile shows **FABRIC · 200G** in green with live numbers.

- [ ] **Step 6: Prove the degraded state is real, not theoretical**

The whole feature exists to catch a silent WiFi fallback. Prove it fires:

```bash
# temporarily make the fabric address unreachable from the app's perspective
sudo ip link set dev enp130s0f1np1 down
curl -s http://127.0.0.1:5001/api/system/spark | grep -o '"path": *"[a-z]*"'   # expect "wifi"
sudo ip link set dev enp130s0f1np1 up
```

Expected: `"path": "wifi"` while down (tile goes amber, "DEGRADED — ON WIFI"), and back to `"fabric"` after `up`.
**Note:** the service caches for 10s — wait ~10s after each toggle before re-checking.

- [ ] **Step 7: Commit**

```bash
git add soveryn/app/templates/command_center.html
git commit -m "feat(spark): Mission Control Spark tile — amber on silent WiFi fallback"
```

---

### Task 5: Full suite green

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite**

Run: `~/miniconda3/envs/soveryn/bin/python -m pytest tests/ -q`
Expected: no new failures vs. the pre-change baseline. If anything fails, fix it before finishing — do not report done on a red suite.

- [ ] **Step 2: Commit any fixes**

```bash
git add -A && git commit -m "test: keep suite green after Spark tile"
```
