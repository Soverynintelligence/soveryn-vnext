# Mission Control — DGX Spark tile

**Date:** 2026-07-14
**Status:** Approved (Jon)

## Purpose

Mission Control (`command_center.html`) tracks the tower only. The DGX Spark is now a
first-class fleet host — it serves Nemotron under vLLM and is reachable over a
200G ConnectX-7 direct link. It needs to be visible.

Two jobs in one tile:

1. **Box health** — alive?, GPU util/temp, unified memory, containers up.
2. **Serving state** — which model, requests in flight, KV-cache utilization.

## The failure mode this exists to catch

The Spark has two paths to the tower:

| Path | Address | Speed |
|---|---|---|
| ConnectX-7 DAC (fabric) | `10.10.10.2` | ~118 Gbit/s measured |
| WiFi | `192.168.86.26` | orders of magnitude slower |

If the fabric drops, **everything keeps working over WiFi — just ~100× slower, with
nothing to announce it.** That presents as "the expensive card stopped working" or
"everything got slow again," and it is invisible to a naive up/down check.

**Therefore: WiFi is a WARNING state, not a healthy one.** A tile that goes green
whenever the Spark merely *answers* would be green while the fabric is dead. The tile
reports *which path answered*.

## Architecture

Chosen approach: **SSH probe from the tower** (no new service on the Spark).

Rejected alternatives:
- *HTTP agent on the Spark* — cleaner to consume, but a new service to deploy,
  keep alive, and auto-start on a freshly-headless box. One more thing that can be
  quietly dead. Promote to this later if the probe grows; the route and UI won't change.
- *Prometheus node_exporter + dcgm-exporter* — two or three more containers, dcgm's
  GB10 unified-memory support is unproven, and custom glue would still be needed.

### 1. `soveryn/app/services/spark_stats.py` (new)

Mirrors the existing `gpu_stats.py` shape: dataclasses, module-level cache, graceful
degrade. Cache TTL **10s** (SSH spawn is ~200ms; the dashboard polls faster than that).

**Probe order — the fallback IS the fabric health check:**

```
try 10.10.10.2    (ssh ConnectTimeout=2)  -> path = "fabric"
else 192.168.86.26 (ssh ConnectTimeout=2) -> path = "wifi"     # DEGRADED
else                                      -> available = False
```

**One SSH round-trip** collects:
- `nvidia-smi --query-gpu=utilization.gpu,temperature.gpu --format=csv,noheader,nounits`
- `free -b` — **unified memory comes from here, NOT nvidia-smi.** On GB10,
  `nvidia-smi` reports `memory.total = [N/A]` because memory is unified. Feeding it to
  the existing parser would produce garbage. This is why the Spark needs its own probe
  rather than being a second host in `gpu_stats.py`.
- `docker ps --format '{{.Names}}|{{.State}}'`

**Two HTTP calls** to vLLM on the resolved host (short timeouts):
- `GET :8000/v1/models` — served model id, liveness
- `GET :8000/metrics` — Prometheus text. Parse (names verified against the live
  Spark running vLLM 0.25.0, not guessed):
  `vllm:num_requests_running`, `vllm:num_requests_waiting`, `vllm:kv_cache_usage_perc`

Any failure degrades that sub-section to `None` rather than failing the whole probe —
a dead vLLM must still show a live box.

### 2. `GET /api/system/spark` (in `soveryn/app/routes/api_system.py`)

Same response shape as `/api/system/gpu`:

```json
{
  "available": true,
  "path": "fabric",              // "fabric" | "wifi" | null
  "message": "",
  "host": {"gpu_util_pct": 0, "gpu_temp_c": 45,
           "mem_used_bytes": 0, "mem_total_bytes": 0},
  "containers": [{"name": "nemotron-spark", "state": "running"}],
  "vllm": {"up": true, "model": "nemotron",
           "requests_running": 0, "requests_waiting": 0,
           "kv_cache_pct": 0.0},
  "fetched_at": 0.0
}
```

### 3. Spark tile in `soveryn/app/templates/command_center.html`

| State | Colour | Condition |
|---|---|---|
| Healthy | green | reachable via **fabric** |
| Degraded | amber | reachable via **WiFi** — label "DEGRADED — on WiFi" |
| Down | red | unreachable |

Displays: link path, GPU util/temp, unified memory used/total, vLLM model +
requests running/waiting + KV-cache %, container states.

## Testing

Mocked subprocess + HTTP, following `tests/test_app_api_*.py`:

1. Fabric reachable → `path == "fabric"`, healthy.
2. Fabric down, WiFi up → `path == "wifi"`, **degraded state asserted** (this is the
   whole point of the feature; it must be tested, not assumed).
3. Both down → `available == False`, no exception.
4. `nvidia-smi` returns `[N/A]` for memory → memory still populated from `free`, no
   garbage values, no crash.
5. Box up but vLLM dead → box metrics present, `vllm.up == false`.

## Out of scope

- Historical/time-series metrics. This is a live tile.
- Controlling the Spark from Mission Control (start/stop containers). Read-only,
  consistent with the rest of `/api/system/*`.

## References

- `project_soveryn_connectx7_install_2026_07_13` — the fabric, its addresses, and the
  reboot-persistence gotcha this tile guards against.
- `project_soveryn_spark_vs_blackwell_2026_07_14` — why the Spark is a fleet host.
