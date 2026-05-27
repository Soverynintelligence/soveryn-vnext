# SOVERYN vNext

Clean rebuild of SOVERYN, the local multi-agent system. Built beside the running production instance, not in place of it.

**Source of authority:** `docs/CURRENT_TRUTH_2026-05-23.md`. The active rebuild plan is tracked from `~/soveryn_complete/docs/superpowers/plans/2026-05-27-soveryn-rebuild-phase1-vnext-refactor.md`.

## Status

vNext is a working side-by-side Flask app and Phase 1 platform refactor substrate. It now has:

- 3 active chat agents: Aetheria, V.E.T.T., Scotty
- Explicit agent packages for Aetheria, Ares, Vett, and Scotty
- Aetheria chat and heartbeat surfaces split at the code boundary
- Platform packages for inference, lattice/memory, tools, bus, supervisor, telemetry, and repair recipes
- Compatibility shims for old import paths during the refactor window
- Command center UI, chat UI, sessions, streaming, compatibility routes, validation harness, and code-backup daemon from earlier vnext work

Phase 1 declares structure and preserves current behavior. Later phases build and swap platform components one at a time.

## Layout

```text
soveryn/
├── agents/        # agent policy and entry surfaces
├── app/           # Flask app and route surface, still top-level in Phase 1
├── backup/        # code backup daemon
├── config/        # runtime/config loading
├── inference/     # compatibility shims to platform.inference
├── memory/        # conversation store + lattice compatibility shim
├── platform/      # shared mechanisms
├── tools/         # compatibility shim to platform.tools
└── validation/    # prod-vnext comparison harness
```

Phase 1 verification: `docs/PHASE1_VNEXT_REFACTOR_VERIFY.md`.

## Running tests

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest
```
