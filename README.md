# SOVERYN vNext

Last reviewed: 2026-09-22 by Kernel
Who: see CURRENT_TRUTH §0
Staleness owner: Kernel — re-verifies this README against the tree and CURRENT_TRUTH on each docs pass; Jon arbitrates disputes.
Staleness rule: re-verify against CURRENT_TRUTH per-row dates before relying on this file; update this line on each review.

> **One rule:** if Jon needs it day-to-day, it shows up in **Messages**. Everything else is engine room or a satellite.

## What is SOVERYN

- **What:** a fully local multi-agent AI house and SOVERYN Intelligence LLC (North Carolina). Not a crypto token, DAO, or chain.
- **Where:** Jon-owned hardware — tower + dual DGX Sparks. Models stay local.
- **What's live:** Messages is the house front door. Runtime facts: [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md).

Archived snapshot of an older truth file: `docs/archive/CURRENT_TRUTH_2026-05-23.md` — historical only; live truth is [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md).

## Status

See **CURRENT_TRUTH** for live vs incomplete, [kill list](docs/CURRENT_TRUTH.md#4-kill-list), and hardware. Do not copy those here.

## Public surfaces

Public surfaces: see [CURRENT_TRUTH §1 — What is live](docs/CURRENT_TRUTH.md#1-what-is-live).

## Layout

```text
soveryn/
├── agents/        # agent policy and entry surfaces
├── app/           # Flask app and route surface
├── backup/        # code backup daemon
├── docs/          # truth, notes, runbooks, archive
├── config/        # runtime/config loading
├── inference/     # compatibility shims to platform.inference
├── memory/        # conversation store + lattice compatibility shim
├── platform/      # shared mechanisms
│   └── email/     # citizen email (not armed)
├── tools/         # compatibility shim to platform.tools
└── validation/    # prod-vnext comparison harness

~/teammates/        # Critic/Scout overnight — briefs → Messages
```

Phase / track verify docs live under `docs/` (`PHASE1_…`, `PHASE2_…`, `TRACK2_…`).

## Running tests

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest
```
