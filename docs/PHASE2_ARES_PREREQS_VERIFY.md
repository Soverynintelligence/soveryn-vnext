# Phase 2 Ares Prereqs Verify

**Date:** 2026-05-28
**Plan:** `~/soveryn_complete/docs/superpowers/plans/2026-05-27-soveryn-rebuild-phase2-ares-prereqs.md`
**Implementation repo:** `~/soveryn_vnext`
**Baseline:** Phase 1 close at `06ab490`
**Final HEAD:** `eb8b1cb` before this docs closeout commit

## Result

Phase 2a is implemented as the Ares-prerequisite platform slice. It gives bus, telemetry, supervisor, and the tools registry enough real behavior for Phase 3 to port `agents/ares/daemon.py` without inventing missing platform pieces along the way.

Ares remains a daemon, not an active tool-owning chat agent. The readiness contract proves Ares can publish anomalies, be health-probed, and record telemetry without using LLM inference or invoking tools.

## Final Test Command

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest
```

Final result after Task 7 pre-commit verification:

```text
653 passed in 5.11s
```

The suite may emit the existing `RequestsDependencyWarning` before collection; it is non-fatal.

## Acceptance Criteria

- [x] Bus durability across restart is proven by test; `SQLiteBus` keeps the stateless caller-tracked cursor model.
- [x] Bus Ares event contract is proven with `event_type="anomaly.detected"` and `actor="ares"`.
- [x] Telemetry has real `log()` and `query()` APIs backed by canonical JSONL plus a queryable SQLite mirror.
- [x] Telemetry uses `source`, `event_type`, and `level`; there is no `audit` level. Tool audits are `event_type="tool.invoked"`.
- [x] Supervisor health checks use the pull/probe model: `HealthProbe.check(HealthCheck) -> HealthCheckResult`.
- [x] Supervisor returns honest probe states: healthy target `ok`, unhealthy reachable target `fail`, unreachable or unknowable target `unknown`.
- [x] Tools registry validates args against `ToolSpec.schema` with `jsonschema` before dispatch.
- [x] Invalid tool args raise `ToolArgError(ValueError)` and still emit a failed audit event.
- [x] Tools registry default audit hook writes queryable telemetry at `source="platform.tools.registry"`, `event_type="tool.invoked"`, `level="info"` or `"error"`.
- [x] Permission remains enforced by the existing `(agent, tool_name)` composite-key lookup; no separate permission exception was added.
- [x] `tests/test_ares_readiness.py` proves a fake Phase-3-style Ares daemon can publish, be health-probed, and record findings through real platform APIs.
- [x] The Ares readiness path has a runtime import guard that fails if `soveryn.platform.inference` is imported.
- [x] Full suite remains green after the platform changes.

## Commit Trail

```text
eb8b1cb test: prove Ares platform readiness contract
7f25072 platform: route tool audits to telemetry
a2b656c platform: validate tool registry args
e90d217 platform: implement supervisor health probes
e00abc7 platform: add telemetry log and query API
0649dd9 test: verify bus durability for Ares prerequisites
3dd41b0 docs: record Phase 2 Ares prereqs baseline
```

## What Phase 2 Does NOT Include

- No lattice writes, Attic population, or Region rewrite. That remains Phase 2b.
- No real Ares behavior port. `agents/ares/daemon.py` still raises the honest not-ported error until Phase 3.
- No Scotty repair execution or recipe runner activation.
- No heartbeat surface port.
- No Flask route or chat path rewiring through the bus.
- No production cutover.
- No compatibility shim removal.
- No tool invocation by Ares. Ares is still modeled as a daemon that detects and reports; it is not an active tool-owning agent.

## Review Notes

- The bus implementation was not rewritten in Phase 2. Task 2 proved the Phase 1 implementation already persists events across restart and supports independent stateless cursors.
- The supervisor model stayed probe/pull. No `report_health`, `fetch_health`, or `HealthStatus` push API was added.
- Telemetry uses normal levels: `debug`, `info`, `warning`, `error`. Audit semantics are represented by event type, not a special level.
- The Ares-readiness test intentionally uses a file heartbeat target for deterministic health checks. Fresh file returns `ok`; missing file returns `unknown`.

## Sign-off

Phase 2a Ares prerequisites are closed. Phase 3 may begin by porting Ares behind the contract in `tests/test_ares_readiness.py`.
