> **One rule:** if Jon needs it day-to-day, it shows up in **Messages**. Everything else is engine room or a satellite.

# SOVERYN vNext

## What is SOVERYN

- **What:** a fully local multi-agent AI house and SOVERYN Intelligence LLC (North Carolina). Not a crypto token, DAO, or chain.
- **Who:** Jon de Oliveira. Live citizens: **Aetheria** (soul), **Kernel** (build), **Eve** (research + ship). Vett and Scotty are not in `ACTIVE_AGENTS` and have no Messages thread — their work is folded into Eve and Kernel respectively.
- **Roster tiers:** *live citizens* = Aetheria / Kernel / Eve (in `ACTIVE_AGENTS`, have Messages threads). *folded* = Vett⇑Eve, Scotty⇑Kernel (no `ACTIVE_AGENTS` entry, no Messages thread). *teammates* = Critic / Scout (overnight briefs into Messages, not chat peers).
- **Where:** Jon-owned hardware — tower + dual DGX Sparks. Models stay local.
- **What's live:** Messages is the house front door. Runtime facts: [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md) (rotated 2026-08-31). Public buy: History's Ledger ($19 / one week) on [soverynintelligence.com/ledger](https://soverynintelligence.com/ledger).
- **What's not:** no cloud dependency, no token. Citizen email is designed and **not armed**. Seneca does not quote dollars.

Archive of an older truth file: `docs/archive/CURRENT_TRUTH_2026-05-23.md` — **do not treat as live**; the only live truth is [`docs/CURRENT_TRUTH.md`](docs/CURRENT_TRUTH.md).

## Status

See **CURRENT_TRUTH** for live vs incomplete, [kill list](docs/CURRENT_TRUTH.md#kill-list), and hardware. Do not copy those here.

## Public surfaces

| Surface | What it actually is | Last verified | Verified by |
|---------|---------------------|---------------|-------------|
| [soverynintelligence.com](https://soverynintelligence.com) | Customer site. Sells **History's Ledger** — $19, one week, Mon–Fri, fourteen held documents; Atticus stops when the page isn't held. Lab is not for sale. | 2026-09-09 (Kernel — fetched /ledger; $19 one-week checkout copy live) | Kernel |
| PondWright / CWG | Case study + contractor stack (estimating, intake, field tooling). Referenced from the customer site; links to pondwright.com. Catalog honesty; CWG brand is oasis/serenity, not MAP. | 2026-09-10 (Kernel — pondwright.com fetched directly; live PondWright guide + CWG Sandhills content, no price quotes — matches row description) | Kernel |
| Seneca | Live public agent + lead capture. **Does not quote dollars.** Internal skeleton: `docs/ops/soveryn-quote-skeleton.md`. | 2026-09-09 (Kernel — soverynintelligence.com/seneca serves the same customer-site page, no dollar quote present; no separate Seneca copy found) | Kernel |
| Atticus | Fact-guard on History's Ledger (halts when the page isn't held). In-house at `:8500`; not a standalone public product. | pre-launch (not verified as a public surface 2026-09-09) | Kernel |
| TGTHRmess | In-house TGTHR helper (Messie Qwen3.5-9B Q6 on `:5066`); not a public internet product. | pre-launch (not verified as a public surface 2026-09-09) | Kernel |
| Messages | House OS (phone). Not a public product. | n/a (house-internal) | n/a |

`Last verified` dates are set by whoever last re-checked the row against the live surface; `Verified by` names that citizen (Kernel = house build brain, re-fetched live). `pre-launch` means the surface is not live to the public internet — do not treat it as a verified public product. Post-rotation re-checks: soverynintelligence.com re-checked 2026-09-09, PondWright 2026-09-10 (rotation date 2026-08-31).

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
