# Phase 2c Supervisor Orchestration Verification

Date: 2026-05-31
Baseline: `926 passed`
Baseline freeze: `6500f74` (`docs: freeze Phase 2c baseline (HEAD + tests)`)
Final implementation head before this docs commit: `06341a5`
Final tests: `949 passed`

## Acceptance

- `soveryn.platform.supervisor.readiness.wait_for_health` exists as the boot-gate primitive for supervisor-preflight checks.
- Systemd user units exist for the router, vNext app, Ares daemon, and orchestration target.
- The router unit runs `llama-server` on `:8090` with restart-on-failure behavior and a cold-start timeout.
- The vNext unit waits for the router `/props` endpoint before starting the Flask app on `:5001`.
- The Ares unit waits for vNext `/health`, runs with `Restart=no`, and stays detection-only.
- `scripts/install_systemd_units.sh` installs and removes the user units idempotently with `--install`, `--uninstall`, and `--dry-run`.
- `python -m soveryn.status` prints the existing preflight report without reimplementing it.

## What Shipped

- `soveryn/platform/supervisor/readiness.py` provides the polling wait primitive and CLI entry.
- `systemd/soveryn-router.service` defines the router user unit.
- `systemd/soveryn-vnext.service` defines the Flask app user unit and its router preflight.
- `systemd/soveryn-ares.service` defines the Ares user unit and its vNext preflight.
- `systemd/soveryn.target` ties the three services together under one orchestration target.
- `scripts/install_systemd_units.sh` installs or removes the units from `~/.config/systemd/user`.
- `soveryn/status.py` wraps `soveryn.app.preflight.run_preflight()` for operator use.
- `tests/test_platform_supervisor_readiness.py`, `tests/test_systemd_units_shape.py`, and `tests/test_status_cli.py` cover the new surface.

## Final Checks

```text
$ /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q
949 passed in 6.25s
```

## Out Of Scope

- No new supervisor daemon was added. Systemd is the supervisor.
- No system units were added. These are user units.
- No new health probe shapes were introduced beyond the existing HTTP and file-heartbeat paths.
- No Ares dry-run flip was added. That remains operator-controlled.
- No router model-server-per-process units were added. The router preset still owns that lifecycle.

## Operational Handoff

1. Run `scripts/install_systemd_units.sh --install` to copy the units into `~/.config/systemd/user`.
2. Use `systemctl --user enable --now soveryn.target` to bring the stack up under one target.
3. Use `python -m soveryn.status` to print the preflight report before a bake or after a change.
4. Keep the bake and the `dry_run=False` decision separate from the code path.

## Sign-Off

Phase 2c closes the supervisor orchestration surface needed to start the stack in the right order, gate startup on health, and install or remove the user units without duplicating preflight logic.
