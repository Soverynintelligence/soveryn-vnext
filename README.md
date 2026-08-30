# SOVERYN vNext

Clean rebuild of SOVERYN, the local multi-agent system. Built beside the running production instance, not in place of it.

**Source of authority:** [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md) (rotated 2026-08-28).  
Archive only: `docs/CURRENT_TRUTH_2026-05-23.md`. Session notes in `docs/notes/` are not authority.

## Status

See **CURRENT_TRUTH** for live vs incomplete, kill list, and hardware. Do not copy those here.

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
Phase 2a verification: `docs/PHASE2_ARES_PREREQS_VERIFY.md`.
Phase 2b-i verification: `docs/PHASE2B_I_VERIFY.md`.
Phase 2b-ii-a verification: `docs/PHASE2B_II_A_VERIFY.md`.
Phase 2b-ii-b1 verification: `docs/PHASE2B_II_B1_VERIFY.md`.
Phase 2b-ii-b2 verification: `docs/PHASE2B_II_B2_VERIFY.md`.
Phase 3a verification: `docs/PHASE3A_ARES_CORE_HARDWARE_VERIFY.md`.
Phase 3b verification: `docs/PHASE3B_ARES_NETWORK_ARCHITECTURE_VERIFY.md`.
Phase 3c verification: `docs/PHASE3C_ARES_OPERATIONAL_CLOSE_VERIFY.md`.
Track 2 verification: `docs/TRACK2_AETHERIA_LATTICE_TOOLS_VERIFY.md`.

## Running tests

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest
```
