# SOVERYN vNext

Last reviewed: 2026-10-22 by Forge
Who: see CURRENT_TRUTH §0
Staleness owner: Forge (house desk clerk) — re-verifies this README against the tree and CURRENT_TRUTH on each docs pass. CURRENT_TRUTH re-observe (weekly, Monday) is Kernel's, per the CURRENT_TRUTH staleness rule. Jon arbitrates disputes.
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
soveryn_vnext/
├── soveryn/       # the package
│   ├── agents/        # agent policy and entry surfaces
│   ├── app/           # Flask app and route surface
│   ├── backup/        # code backup daemon
│   ├── config/        # runtime/config loading
│   ├── inference/     # compatibility shims to platform.inference
│   ├── memory/        # conversation store + lattice compatibility shim
│   ├── platform/      # shared mechanisms
│   │   └── email/     # citizen email (not armed)
│   └── validation/    # prod-vnext comparison harness
├── docs/          # truth, notes, runbooks, archive
│   ├── notes/         # dated notes (not authority)
│   ├── runbooks/      # operational runbooks (env vars, secrets backup)
│   └── archive/       # archived truth snapshots
├── packages/      # standalone apps: soveryn-cli, soveryn-console, soveryn-acttruth
├── scripts/       # operator + harness scripts (soveryn-pi, soveryn-aider, see.sh, backups)
├── systemd/       # unit files (install via scripts/install_systemd_units.sh)
├── demos/         # demo surfaces
├── tests/         # pytest suite
├── config/        # repo-level config trees (pi/, runtime profiles)
├── data/          # runtime state: DBs, black_box receipts, lattice, medic, automations
├── logs/          # service logs
├── backups/       # nightly DB/archive snapshots
├── runtime/       # runtime scratch for live processes
├── eval_runs/     # eval outputs
├── scratch/       # throwaway work
├── carolina-redesign/  # CWG site redesign work
└── tmp/           # ephemeral

~/teammates/        # Critic/Scout overnight — briefs → Messages
```

Phase / track verify receipts live under `docs/archive/2026-phase-receipts/`.

## Running tests

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest
```

## Host tools

Pi / Kernel file search uses `fd` from `PATH` (not a bundled binary). Install from the package manager:

```bash
# Debian / Ubuntu
sudo apt install fd-find
mkdir -p ~/.local/bin
ln -s "$(command -v fdfind)" ~/.local/bin/fd   # fdfind is the Debian name

# macOS
brew install fd
```
