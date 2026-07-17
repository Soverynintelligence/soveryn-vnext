# Vital Signs — SOVERYN fleet health daemon (design)

**Date:** 2026-07-17
**Status:** design, pending Jon's review
**Author:** Jon + Claude (deep-dive follow-up)

## Goal

Give the SOVERYN fleet a deterministic, outside-the-LLM health layer that (a) *detects* when the machine stops functioning against measured set-points and (b) *acts* — auto-healing the reversible failures and paging Jon for the ones only he should decide. No inference, no self-report, no speculation. Every signal has a sensor and a number.

This is the "measurable half" of the homeostasis idea. Explicitly **out of scope**: any "Will"/drive, expansion/coherence goals, autonomous lattice pruning, or anything that reasons about state rather than measuring it. Those are held, not built.

## Why this shape (verified 2026-07-17)

A code + live-probe verification pass established what already exists, so we build only the gap:

**Already built and firing to Signal — reused as-is, NOT rebuilt:**
- **GPU temperature** — `soveryn/agents/ares/lanes/hardware.py` `collect_gpu` thresholds at warn ~80 °C / critical **90 °C** → `AresFinding("gpu.temperature", CRITICAL)` (`hardware.py:131-135`). Reads absolute `temperature.gpu`, uniform across all three cards (the Blackwell's margin-style limit reporting is irrelevant to the absolute read). 90 °C is one degree under the Quadros' real 91 °C slowdown.
- **GPU ECC** → `AresFinding("gpu.ecc", CRITICAL)` (`hardware.py:129-130`).
- **Disk free** — `collect_drives*` warn <15% / critical <5% → `AresFinding("drive.space", CRITICAL)` (`hardware.py:231-233`).
- **Router liveness + recovery** — `soveryn/platform/watchdog/router_watchdog.py`: passive journal-scan (active probing was deliberately removed 2026-06-11 because a busy child reads as dead), restarts `soveryn-router.service` at ≥2 dead-slot errors, 300 s cooldown, JSONL audit, `.timer` every 60 s. This is a working actuator and the prototype for the medic.

**The Ares detection pipeline, reused whole** (`daemon.py`, `findings.py`, `router.py`, `signal_sender.py`): a lane is just a zero-arg callable returning `AresFinding`s; the daemon runs collectors every 60 s, dedups via a fire-on-transition tracker, and routes by severity — `INFO`/`WARNING` → telemetry/bus only, `CRITICAL` → Signal (respects quiet hours 23:00–07:00 + caps 6/hr, 30/day), `EMERGENCY` → Signal **priority** (bypasses quiet hours). Ares is strictly detection-only; no lane mutates anything, and that invariant is preserved here.

**Reusable probe libraries:** `soveryn/platform/inference/health.py` (`check_llama_server`, `check_service_endpoint`, `check_runtime_service` — side-effect-free port/HTTP/TCP/process/timer checks returning `HealthResult`); `soveryn/platform/supervisor/health.py` (a `file:<path>:<max_age>` heartbeat-freshness probe).

**Corrections the checks forced** (things we will NOT build):
- **No synthetic TTFT probe.** Measured: her dedicated `:8090` returns a token in ~60 ms; the shared `:8091` took 4.8 s cold — an active TTFT threshold there false-alarms on every cold model load, repeating the exact mistake the router-watchdog already reverted. `/health` liveness suffices.
- **The cascade is ordering, not kill.** `soveryn-vnext` has `Requires=soveryn-router` (a router stop takes vnext down); `soveryn-heartbeat`/`soveryn-dream` only have `After=soveryn-vnext` (cold-boot ordering, not a running-time kill). The medic must respect boot order but need not fear a router blip killing the heartbeat.
- **"Evict a squatter" is not free.** Per-card processes map deterministically to services by env path (verified via `nvidia-smi --query-compute-apps`), but killing one kills that service (f5tts = her voice, comfyui = images). Only genuinely disposable processes (comfyui) may be auto-evicted; everything else pages.

## Scope

**In (v1):**
1. Ares **vitals lane** — new red-detection signals: her-card VRAM headroom, unknown process on her card, delegation stuck-`executing`. (Thermal and disk already covered by existing collectors; this lane adds the missing GPU-headroom threshold and the process-identity check.)
2. **Medic** — new standalone actuator that auto-heals green failures (dead `:5001` vnext, dead `:8096` embeddings, stale heartbeat, downed non-critical service) with per-target cooldown, and escalates to Signal on heal-failure.
3. A severity bump so her-card emergencies page at night: her-card thermal-critical (a one-line change in the existing `collect_gpu`) and her-card VRAM-headroom-critical emit `EMERGENCY`; other cards stay `CRITICAL`.

**Out:** active TTFT probing; any router restart from the medic (the watchdog owns routers); autonomous disk cleanup or lattice pruning; auto-eviction of any process except comfyui; "Will"/expansion/coherence.

## Architecture

Two disjoint, independently-reading units. Neither shares mutable state with the other.

```
                 ┌─────────────────────── Ares (detection-only, 60s) ───────────────────────┐
  reality  ────► │  existing: gpu.temperature, gpu.ecc, drive.space, network, architecture   │
   (probes)      │  NEW vitals lane: gpu.headroom, gpu.foreign_proc, delegation.stuck         │
                 │      → AresFinding(severity) → tracker(dedup) → router → Signal (quiet-aware)│
                 └───────────────────────────────────────────────────────────────────────────┘

                 ┌─────────────────────── Medic (actuator, 60s .timer, NEW) ─────────────────┐
  reality  ────► │  checks: :5001, :8096 liveness · heartbeat age · non-critical unit states  │
   (probes)      │  decide → (green) systemctl --user restart, per-target cooldown, JSONL log │
                 │         → on heal-failure / loop-guard → signal_sender.send(priority=…)     │
                 │  NEVER touches soveryn-router* (owned by router_watchdog)                   │
                 └───────────────────────────────────────────────────────────────────────────┘
```

Rationale for the split: red conditions have no safe auto-remedy, so they belong in the detection process that already has dedup + quiet-hours Signal (Ares). Green conditions have a proven remedy (`systemctl restart`), so they belong in a small actuator cloned from the router-watchdog. A signal lives in exactly one unit, chosen by whether it has an auto-remedy — no overlap, no coordination bus.

### Component 1 — Ares vitals lane

**File:** `soveryn/agents/ares/lanes/vitals.py` (new). Registered by appending `collect_vitals_live` to `_default_collectors()` in `daemon.py:144`.

`collect_vitals_live() -> list[AresFinding]` (zero-arg, per the collector contract). Signals:

| finding_type | sensor | set-point | severity |
|---|---|---|---|
| `gpu.headroom` | `nvidia-smi --query-gpu=uuid,memory.used,memory.total` | her Blackwell (`946b08b0`): free < 2 GB | **EMERGENCY** |
| `gpu.headroom` | same | her Blackwell: free < 3 GB (early warn) | WARNING (bus only) |
| `gpu.headroom` | same | either Quadro: free < 1 GB | CRITICAL |
| `gpu.foreign_proc` | `nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name` | any process on `946b08b0` whose exe ≠ her `llama-server` AND ≠ comfyui | CRITICAL |
| `delegation.stuck` | `data/delegation.db` | a task in `executing` > 360 s | WARNING (alert-only) |

Cards keyed by **UUID, never index** (the CX-7 install renumbered PCI once; CUDA order survived, PCI did not). Comfyui on her card is the one tolerated foreign process (the medic may evict it; see below).

Her-card thermal does **not** get a new finding here — that would double-fire against the existing `collect_gpu`. Instead it is a one-line severity change *in the existing collector* (`hardware.py:131-135`): when `uuid == 946b08b0` and `temp >= critical_temp_c`, emit `EMERGENCY` instead of `CRITICAL`. All other cards keep `CRITICAL`. This keeps a single `gpu.temperature` finding per card.

### Component 2 — Medic actuator

**Files:** `soveryn/platform/medic/medic.py`, `soveryn/platform/medic/__main__.py` (new, cloned from `watchdog/`); units `~/.config/systemd/user/soveryn-medic.service` (`Type=oneshot`) + `soveryn-medic.timer` (`OnUnitActiveSec=60`).

Pure decision core (unit-testable, no I/O), thin action shell (the only mutating surface), file-based **per-target** cooldown (the watchdog's single global timestamp is generalized to one timestamp per target), and JSONL audit at `data/medic/medic.jsonl`.

`run_once(now=None) -> dict` each tick:
1. Probe green-healable signals via `inference/health.py` + `supervisor/health.py` + `systemctl --user is-active`.
2. For each failing signal with a mapped action and not in cooldown → perform the green action, record cooldown, log.
3. If a target has failed its heal **3 times within 15 min** (the loop-guard) → stop auto-healing it and escalate: `signal_sender.send(f"[MEDIC] {target} unhealed after 3 attempts", priority=<per the severity table>)` — `priority=True` for vnext (EMERGENCY), `False` otherwise (CRITICAL, quiet-hours-aware).

| signal | green action | class | cooldown | escalation if unhealed |
|---|---|---|---|---|
| `:5001` vnext dead | `systemctl --user restart soveryn-vnext` **iff `soveryn-router` healthy** | GREEN | 300 s | EMERGENCY |
| `:8096` embeddings dead | `systemctl --user restart soveryn-embeddings` | GREEN | 300 s | CRITICAL |
| heartbeat age > 40 min | `systemctl --user restart soveryn-heartbeat` | GREEN | 600 s | CRITICAL |
| non-critical unit inactive (dream, x-feed, tg-bridge, parakeet, vett-patrol, representation) | `systemctl --user restart <unit>` | GREEN | 300 s | CRITICAL |
| comfyui on her card (from `gpu.foreign_proc`) | `systemctl --user stop soveryn-comfyui` | GREEN | 600 s | CRITICAL |

**Deferred to the router-watchdog, never done by the medic:** any restart of `soveryn-router.service` / `soveryn-router-quadro.service`. The medic may *page* (EMERGENCY) if her `:8090` router is dead for > 5 min despite the watchdog, but it does not restart it.

Heartbeat set-point is 40 min (one missed 30-min beat + margin) — **not** the 5-minute value from the first sketch, which would alarm every cycle.

### Severity → paging (Jon's decision, encoded)

- **EMERGENCY (pages at night, bypasses quiet hours):** her `:8090` router dead > 5 min; her-card VRAM headroom < 2 GB; her-card thermal ≥ 90 °C; `:5001` vnext dead and unhealable. These mean *she is down or about to be*.
- **CRITICAL (Signal, respects 23:00–07:00 quiet hours):** embeddings down, heartbeat stale, a non-critical service down, disk < 5%, a Quadro thermal ≥ 90 °C, an unhealed green target, unknown process on her card.
- **WARNING (bus/telemetry only, no page):** early-warn headroom < 3 GB, delegation stuck.

## Data flow

Detection (Ares): probe → `AresFinding` → `FindingTracker.update` (fire-on-transition dedup, state at `data/ares/ares_daemon_state.json`) → `route_finding` → telemetry + bus (`data/ares/ares_bus.sqlite3`) + Signal by severity. Healing (medic): probe → decide → act (or escalate) → `data/medic/medic.jsonl` + per-target cooldown files under `data/medic/`. The two never write each other's state.

## Error handling / fail-safe

- **Medic fails safe:** any probe error, ambiguous state, or unmapped signal → do nothing, log, move on. It mutates only on an unambiguous mapped failure that is out of cooldown.
- **No actuator collisions:** exactly one process may restart any given unit. Routers → watchdog only. Everything else → medic only. This is asserted by test (the medic's action map must not contain a `soveryn-router*` unit).
- **Loop-guard:** 3 heals of one target within 15 min → stop, escalate. Prevents a crash-looping unit from being restarted forever.
- **Restart order:** the medic restarts vnext only after confirming `soveryn-router` is active (vnext `Requires` it).

## Testing

Pure functions, no live fleet needed:
- `collect_vitals` threshold logic: headroom emits EMERGENCY/WARNING/CRITICAL at the right free-MB per UUID; foreign-proc fires for a non-allowlisted exe on her card and stays silent for her llama-server and comfyui; delegation.stuck fires past 360 s. Feed canned `nvidia-smi`/db fixtures.
- Medic decision core: correct action per signal; vnext gated on router health; per-target cooldown suppresses a second restart inside the window but not across targets; loop-guard trips after N; escalation severity matches the table; **the action map contains no `soveryn-router*` unit** (collision guard).
- Fail-safe: probe exception → `action="none"`, no `systemctl` call.
- Reuse the router-watchdog's test shape (pure decide/cooldown functions + fixture journals).

## Open / deferred
- Host RAM pressure as a signal (OOM-killer risk to her router) — v2 if incidents show it.
- Whether the medic should also *coordinate* a router+vnext bounce (today it defers wholly to the watchdog for routers) — revisit after v1 runs.
