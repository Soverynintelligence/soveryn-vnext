Last reviewed: 2026-09-17 by Kernel

> **One rule:** if Jon needs it day-to-day, it shows up in **Messages**. Everything else is engine room or a satellite.

# SOVERYN vNext

## What is SOVERYN

- **What:** a fully local multi-agent AI house and SOVERYN Intelligence LLC (North Carolina). Not a crypto token, DAO, or chain.
- **Who:** Jon de Oliveira. Live citizens: **Aetheria** (soul), **Kernel** (build), **Eve** (research + ship). Vett and Scotty are not in `ACTIVE_AGENTS` and have no Messages thread — their work is folded into Eve and Kernel respectively.
- **Roster tiers:** *live citizens* = Aetheria / Kernel / Eve (in `ACTIVE_AGENTS`, have Messages threads). *folded* = Vett⇑Eve, Scotty⇑Kernel (no `ACTIVE_AGENTS` entry, no Messages thread). *teammates* = Critic / Scout (overnight briefs into Messages, not chat peers).
- **Where:** Jon-owned hardware — tower + dual DGX Sparks. Models stay local.
- **What's live:** Messages is the house front door. Runtime facts: [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md).
- **What's not:** no cloud dependency, no token. Citizen email is designed and **not armed**. Seneca does not quote dollars.

Archived snapshot of an older truth file: `docs/archive/CURRENT_TRUTH_2026-05-23.md` — historical only; live truth is [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md).

## Status

See **CURRENT_TRUTH** for live vs incomplete, [kill list](docs/CURRENT_TRUTH.md#kill-list), and hardware. Do not copy those here.

## Public surfaces

Public surfaces: see docs/CURRENT_TRUTH.md §1.

## Layout

```text
soveryn/
├── agents/        # agent policy and entry surfaces
├── app/           # Flask app and route surface
├── backup/        # code backup daemon
├── config/        # runtime/config loading
├── inference/     # compatibility shims to platform.inference
├── memory/        # conversation store + lattice compatibility shim
├── platform/      # shared mechanisms
├── tools/         # compatibility shim to platform.tools
└── validation/    # prod-vnext comparison harness
```

Phase / track verify docs live under `docs/` (`PHASE1_…`, `PHASE2_…`, `TRACK2_…`).

## Running tests

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest
```
