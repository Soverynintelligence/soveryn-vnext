# soveryn (SOVERYN CLI)

Branded coding harness wrapping **Pi Coding Agent 0.74.2**.

## Parallel harnesses — shared profiles SSOT

`kernel` / `soveryn-pi` and `soveryn` share `config/soveryn-cli/profiles.json`.
Kernel writes `config/pi/`; soveryn writes `config/soveryn-cli/`. Active brain files stay in sync.

| Path | Role |
|---|---|
| `~/bin/kernel` → `scripts/soveryn-pi` | Kernel launcher (`SOVERYN_HARNESS=kernel`) |
| `config/pi/` | Kernel Pi agent dir (models/settings regenerated from profiles) |
| `~/bin/soveryn` → this package | Branded CLI harness |
| `config/soveryn-cli/` | soveryn Pi agent dir + **profiles.json SSOT** |
| `~/.soveryn/kernel_brain` ↔ `soveryn-cli-profile` | Active brain (kept in sync) |

## Commands

```bash
soveryn                  # launch Pi TUI (new session if last thread is stale)
soveryn resume           # pick up the last thread
soveryn resume 01a0898b  # reload by partial UUID
soveryn sessions         # list recent transcripts
soveryn --new            # skip resume even on a fresh thread
soveryn code             # same as launch
soveryn use flash        # set active profile
soveryn use glm          # refuses loudly while parked
soveryn model            # interactive picker
soveryn status           # active + health + pi version
soveryn doctor           # status + paths + policy gates
soveryn doctor --gates    # policy gates only
soveryn doctor --self-test # assertExact self-test
soveryn --flash --build  # one-shot flags
soveryn --glm            # error if parked — never silently Flash
soveryn unpark glm --dry-run     # Lab steps (no swap)
soveryn unpark glm --if-healthy  # enable if :8001 already has glm-5.3-flash
soveryn unpark glm --confirm     # OWNER: may stop Flash-Next, start EXL3
soveryn park glm --dry-run
soveryn park glm --confirm       # OWNER: stop GLM, restore Flash-Next
```

GLM unpark is **not** hot-standby: needs both Sparks; stops Flash-Next first. See `SOVERYN.md`.

## Profiles (SSOT)

`config/soveryn-cli/profiles.json` drives generated `models.json` / `settings.json` in the same directory.

- `flash` → `http://127.0.0.1:8888/v1` / `qwen3.8-flash-next` (live)
- `glm` → `http://10.10.10.2:8001/v1` / `glm-5.3-flash` (park/unpark is owner-gated; `soveryn status` shows live truth, `doctor` flags parked-but-live drift)
- `aetheria` → `http://127.0.0.1:8090/v1` / `aetheria` (live)

Provider ids: `soveryn-flash`, `soveryn-glm`, `soveryn-aetheria`.

## Install (this machine)

```bash
ln -sfn "$HOME/soveryn_vnext/packages/soveryn-cli/bin/soveryn" "$HOME/bin/soveryn"
# ensure ~/bin is on PATH
soveryn doctor
```

Requires Node 20+ and `pi` 0.74.2 on PATH (nvm).


## Option 2 chrome (dark lab)

Pre-launch splash + status HUD: large monospace **SOVERYN** wordmark, cyan/amber accents on near-black, active brain + ONLINE.

- Theme: Pi `soveryn-lab` (copied into `config/soveryn-cli/themes/` and `config/pi/themes/` on launch)
- Skip splash: `SOVERYN_NO_SPLASH=1`
- Splash is local-only (<100ms; no network)

```bash
soveryn status          # branded HUD
SOVERYN_NO_SPLASH=1 soveryn -p "hi"   # quiet launch

## Spec

See `docs/SOVERYN-CLI-HARNESS-SPEC.md` (adapted here for parallel install).

## Shell alias conflict

Interactive bash on this machine has:

```bash
alias soveryn='cd ~/soveryn_complete && conda activate soveryn && bash start.sh'
```

That **shadows** `~/bin/soveryn`. Until you rename/remove the alias (e.g. `soveryn-legacy`), use:

```bash
unalias soveryn   # current shell
# or:
command soveryn status
~/bin/soveryn status
```

Do not confuse with `kernel` / `soveryn-pi` (untouched).

## Presets + code-mode (borrowed from dsh spirit)

Pi 0.74.2 `--tools` allowlists — no `@deepseek-ai/dsh` (Node 22 / Web-UI deferred).

```bash
soveryn --minimal              # bash+edit only
soveryn --preset standard      # full built-ins (default)
soveryn --code-mode --build    # anti-roundtrip append hint
```

Ledger: `config/soveryn-cli/BORROWED-FROM-DEEPSEEK.md`.

## Failure-mode hardening

See `config/soveryn-cli/NOTES-failure-modes.md` — conservative Flash compaction + prompt anti-patterns against retry burn and compact-chase loops.


## Policy gates (native)

See `config/soveryn-cli/POLICY-GATES.md` (analysis from Kernel `~/soveryn-harness/RESEARCH.md` §4).

- Code: `packages/soveryn-cli/src/policy/`
- Bounded print: `limits.maxPrintSeconds` (default 120) or `SOVERYN_PRINT_TIMEOUT_MS`
- `soveryn doctor --gates` / `--self-test`
