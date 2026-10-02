# Phase 3b Ares Network + Architecture Verification

Phase 3b extends the Phase 3a Ares host sentinel with the two remaining day-one detection lanes: network and architecture. Ares remains detection-only, no-LLM, and dry-run-first.

## Baseline

- Baseline commit: `f524a6a tune(aetheria): bound Qwen reasoning budget per request`
- Baseline gate commit: `36ee2be docs: freeze Phase 3b baseline (HEAD + tests)`
- Baseline tests: `809 passed`; Ares readiness: `1 passed`

## Commit Trail

```text
6b9be1d feat(3b): wire network and architecture lanes into Ares daemon
b09c855 feat(3b): ares architecture lane retired agents and tool ownership
6ef4156 feat(3b): ares architecture lane raw I/O invariant
6ea575b feat(3b): ares network lane service-presence collector
a86ee49 feat(3b): ares network lane port-listener collector
36ee2be docs: freeze Phase 3b baseline (HEAD + tests)
```

## Final Checks

```text
$ /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q
837 passed in 5.80s
```

```text
$ /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_ares_readiness.py -q
1 passed in 0.03s
```

## Acceptance

- `_default_collectors()` now returns five collectors: GPU, CPU, drives, network, architecture.
- `collect_network_live()` runs `ss -H -tlnp` once per scan tick and feeds the same snapshot into listener-delta and service-presence parsers.
- Public-interface listener not allow-listed by `(port, process)` emits `Severity.EMERGENCY`.
- Missing expected loopback service emits `Severity.CRITICAL`.
- `collect_architecture_live()` composes raw-I/O, retired-agent package, and tool-ownership checks.
- Dry-run remains the daemon default and suppresses Signal even for EMERGENCY findings.
- `tests/test_ares_readiness.py` remains green; no LLM inference path is imported by Ares.

## What Shipped

Network lane:
- Loopback listener not in `ARES_NET_LOOPBACK_ALLOWLIST` -> `WARNING`.
- Public-interface listener not in `ARES_NET_PUBLIC_ALLOWLIST` -> `EMERGENCY`.
- Public allow-list entries are `port:process`, not port-only; `0.0.0.0:22` owned by `nc` still alerts.
- Missing expected loopback listener from `ARES_NET_EXPECTED_LOOPBACK` -> `CRITICAL`.

Architecture lane:
- Files under `soveryn/agents/` may not import `sqlite3`, `requests`, `urllib`, or `http.client` directly.
- Retired packages `scout`, `vision`, `tinker`, and `aetheria_public` must not exist under `soveryn/agents/`.
- Tool ownership check flags tools owned by inactive agents when registry introspection is available.

## Out Of Scope

- Memory/identity lane: Attic no-leak and lattice integrity stay in a future phase.
- Hygiene lane: issue queues and similar checks stay deferred.
- Live Signal alerting by default: `dry_run=True` remains the default; live alerting is an operator flip after bake.
- UDP listener coverage: Phase 3b is TCP listener coverage only.
- Remediation or acting: Ares detects and reports only. Scotty owns repair in a later phase.
- Replacing prod Ares: vnext Ares still runs beside prod during dry-run bake.
- Per-lane independent schedulers: all collectors run on each `scan_once` tick.

## Allow-List Tuning Protocol

1. Run vnext Ares in dry-run mode with the Phase 3b lanes enabled.
2. Review telemetry and bus output for network and architecture findings.
3. Add legitimate loopback listeners to `ARES_NET_LOOPBACK_ALLOWLIST`.
4. Add legitimate public listeners to `ARES_NET_PUBLIC_ALLOWLIST` as `port:process` entries only after verifying the process owner.
5. Add expected load-bearing loopback services to `ARES_NET_EXPECTED_LOOPBACK`; remove entries only when a service is intentionally retired.
6. Fix architecture findings at source when possible. If an exception is intentional, record it here before treating it as accepted.
7. After 72 hours of clean dry-run telemetry, flip `dry_run=False` operationally to enable Signal alerting.

## EMERGENCY Tier Note

After Phase 3b, EMERGENCY has a real attack-signal collector behind it. A public-interface listener appearing outside the `(port, process)` allow-list will route as EMERGENCY and will reach Signal once dry-run is disabled. Verify the public allow-list before flipping live.

## Sign-Off

Phase 3b is complete. Ares now scans hardware, network, and architecture lanes every tick in dry-run mode, with no LLM dependency and no remediation behavior.
