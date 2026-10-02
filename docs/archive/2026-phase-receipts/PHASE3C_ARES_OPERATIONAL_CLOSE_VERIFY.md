# Phase 3c Ares Operational Close Verification

Date: 2026-05-31
Baseline: `1a7bbed` (think-markup strip)
Baseline freeze: `cde8241` (`docs: freeze Phase 3c baseline (HEAD + tests)`)
Final implementation head before this docs commit: `ec8ee4d`
Final tests: `899 passed`; Ares readiness: `1 passed`

## Acceptance

- Ares has a runnable production launcher at `python -m soveryn.agents.ares`.
- The launcher defaults to `dry_run=True` and accepts `--no-dry-run`, `--interval-seconds`, and `--iterations`.
- `SIGTERM` and `SIGINT` request clean shutdown between scans.
- The network lane classifies all of `127.0.0.0/8` as loopback and treats loopback-bound `llama-server` listeners as trusted regardless of dynamic port.
- `python -m soveryn.agents.ares.snapshot` runs network + architecture once, prints a markdown report, and exits non-zero when EMERGENCY/CRITICAL findings exist.
- The snapshot verifier is side-effect free: no telemetry writes, no bus publishes, no Signal.
- Hardware lane checks stay out of the snapshot verifier.

## What Shipped

- `soveryn/agents/ares/__main__.py` provides the daemon launcher.
- `soveryn/agents/ares/daemon.py` now accepts a shutdown callback for bounded stop requests between scans.
- `soveryn/agents/ares/lanes/network.py` now uses `ipaddress.ip_address(bind).is_loopback` and a loopback process-name allow-list.
- `soveryn/agents/ares/snapshot.py` provides the live snapshot verifier and markdown formatter.
- `tests/test_ares_launcher.py`, `tests/test_ares_network_lane.py`, and `tests/test_ares_snapshot_verifier.py` cover the launcher, network lane, and snapshot contract.

## Final Checks

```text
$ /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q
899 passed in 6.48s
```

```text
$ /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m soveryn.agents.ares --iterations 1
(exit 0)
```

```text
$ /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m soveryn.agents.ares.snapshot
(exit 1 on the current box; 11 findings total)
```

Live smoke summary:

- EMERGENCY: 8
- CRITICAL: 0
- WARNING: 3
- INFO: 0

The warnings were loopback services (`127.0.0.54:53`, `127.0.0.1:631`, `::1:631`). The EMERGENCY set was dominated by public listeners and by a process-visibility gap in `ss -H -tlnp` when running without elevated privileges.

## Out Of Scope

- ComfyUI exposure stays operational follow-through.
- Tailscale allow-listing stays operational follow-through.
- The 72h dry-run bake stays operational follow-through.
- Flipping `dry_run=False` stays operational follow-through.
- No remediation logic was added; Ares still detects and reports only.

## Operational Handoff

1. Decide whether the daemon will run unprivileged or as root for the bake.
2. If it runs unprivileged, expect `ss -tlnp` to hide process owners for sockets you do not own; the `(port, process)` allow-list will not match those rows cleanly.
3. If you run it as root, the process names become visible and the allow-list entries can match as intended.
4. Use the snapshot verifier output to tune `ARES_NET_LOOPBACK_ALLOWLIST`, `ARES_NET_LOOPBACK_PROCESS_ALLOWLIST`, `ARES_NET_PUBLIC_ALLOWLIST`, and `ARES_NET_EXPECTED_LOOPBACK`.
5. Run the dry-run bake for ~72 hours and only then decide whether to flip `dry_run=False`.
6. Keep the operator notes separate from code changes; the smoke output is environment state, not source state.

## Follow-Ups

- Add a pre-bake operational note for the root-vs-unprivileged choice before the 72h run starts.
- If the daemon stays unprivileged, consider whether the snapshot should document process-name visibility as an explicit limitation during tuning.
- Revisit ComfyUI and Tailscale dispositions before the bake is declared clean.

## Sign-Off

Phase 3c closes the code surface needed for the Ares operational bake. The remaining work is operator tuning and the eventual dry-run-to-live flip.
