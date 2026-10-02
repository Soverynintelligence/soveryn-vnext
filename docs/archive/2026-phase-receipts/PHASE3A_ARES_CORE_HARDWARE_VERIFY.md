# Phase 3a Ares Core + Hardware Verification

Phase 3a ports Ares from an honest stub to a no-LLM, detection-only host sentinel. It proves the full vertical with the hardware lane: collect -> finding -> lifecycle -> router -> telemetry/bus/Signal, with dry-run support for shadow-bake operation beside prod Ares.

## Result

- Status: closed
- Final vnext commit: `f2ed080 agents: wire Ares daemon scan loop`
- Full suite: `701 passed in 5.22s`
- Ares readiness contract: `1 passed in 0.03s`
- Working tree at close: clean

## Commit Trail

```text
98bdb5a docs: record Phase 3a Ares baseline
941ba89 agents: add Ares finding lifecycle tracker
9a6dc48 agents: add pure Ares severity router
0b09944 agents: add Ares Signal sender
3562042 agents: wire Ares router to platform sinks
8b41a69 agents: add Ares GPU hardware lane
b635b47 agents: extend Ares hardware lane collectors
f2ed080 agents: wire Ares daemon scan loop
```

## Acceptance Criteria

- Ares finding model exists with four severities: INFO, WARNING, CRITICAL, EMERGENCY.
- Finding lifecycle is durable and fire-on-transition: new findings route once, ongoing findings do not refire Signal, cleared findings emit cleared telemetry and bus events.
- Router is severity-tiered and injectable:
  - INFO -> telemetry only.
  - WARNING -> telemetry + bus.
  - CRITICAL -> telemetry + bus + Signal.
  - EMERGENCY -> telemetry + bus + priority Signal.
- Signal sender is outbound-only and honors routine rate caps and quiet hours while allowing priority CRITICAL/EMERGENCY sends to bypass both.
- Router uses the real Phase 2a telemetry and bus APIs. Ares severity remains in payload; telemetry level maps to `info`, `warning`, or `error` only.
- Hardware lane collectors are fixture-tested with pure parse functions and thin live wrappers:
  - GPU temperature and ECC from `nvidia-smi` CSV.
  - CPU EDAC and MCE from counter/log-shaped inputs.
  - Drive SMART, free space, and expected mount presence.
- The 2026-05-26 L3 corrected-MCE class is covered as WARNING. Uncorrected MCE is covered as CRITICAL.
- `AresDaemonSurface.scan_once()` runs collectors -> tracker -> router -> sinks and returns the findings tuple.
- `dry_run=True` suppresses Signal while keeping telemetry and bus routing active for shadow-bake.
- `uses_llm` remains `False`; daemon tests include a runtime import guard against `soveryn.platform.inference`.
- `tests/test_ares_readiness.py` remains green.

## Operational Model

Phase 3a does not replace prod Ares. vnext Ares should run alongside prod Ares in dry-run mode first. During the shadow-bake, watch telemetry and bus output for threshold tuning and false positives. Signal alerting stays suppressed in dry-run. After the hardware lane has behaved against real host baselines for a few days, flip `dry_run=False` for live alerting.

A minimal manual dry-run shape is:

```python
from soveryn.agents.ares.daemon import AresDaemonSurface

AresDaemonSurface(dry_run=True).run_forever(interval_seconds=60)
```

A live-alerting shape, only after shadow-bake review, is:

```python
from soveryn.agents.ares.daemon import AresDaemonSurface

AresDaemonSurface(dry_run=False).run_forever(interval_seconds=60)
```

Systemd/service wiring is intentionally not part of Phase 3a; that should be a separate operational step after the dry-run behavior is reviewed.

## Explicit Non-Goals

- Network lane: Phase 3b.
- Architecture lane: Phase 3b.
- Memory, identity, or hygiene lanes: after Phase 2b.
- Remediation or acting on findings: Scotty, Phase 5.
- Prod-Ares replacement: later phase, after vnext covers the remaining prod lanes.
- Real-hardware-dependent test assertions: tests remain fixture-driven so CI/local runs are stable.

## Commands Run

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_ares_readiness.py -q
```
