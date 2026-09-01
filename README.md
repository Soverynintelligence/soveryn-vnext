# SOVERYN vNext

## What is SOVERYN

- **What:** a fully local multi-agent AI house and SOVERYN Intelligence LLC (North Carolina). Not a crypto token, DAO, or chain.
- **Who:** Jon de Oliveira. Live citizens: **Aetheria** (soul), **Kernel** (build), **Eve** (research + ship). Vett is folded into Eve; Scotty’s coding lane is folded into Kernel. Neither is a Messages peer.
- **Where:** Jon-owned hardware — tower + dual DGX Sparks. Models stay local.
- **What's live:** Messages is the house front door. Runtime facts: [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md) (rotated 2026-08-31). Public buy: History’s Ledger ($19 / one week) on [soverynintelligence.com](https://soverynintelligence.com).
- **What's not:** no cloud dependency, no token. Citizen email is designed and **not armed**. Seneca does not quote dollars.

Session notes in [`docs/notes/`](docs/notes/) are not authority. Index: [`docs/notes/INDEX.md`](docs/notes/INDEX.md). Archive of an older truth file: `docs/CURRENT_TRUTH_2026-05-23.md`.

## Status

See **CURRENT_TRUTH** for live vs incomplete, kill list, and hardware. Do not copy those here.

## Public surfaces

| Surface | What it actually is |
|---------|---------------------|
| [soverynintelligence.com](https://soverynintelligence.com) | Customer site. Sells **History’s Ledger** ($19, one week, Atticus stops when the page isn’t held). Lab is not for sale. |
| PondWright / CWG | Case study + contractor stack. Catalog honesty; CWG brand is oasis/serenity, not MAP. |
| Seneca | Live public agent + lead capture. **Does not quote dollars.** Internal skeleton: `docs/ops/soveryn-quote-skeleton.md`. |
| Messages | House OS (phone). Not a public product. |

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
