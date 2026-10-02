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
soveryn doctor --json     # machine-readable: health + drift + config freshness + gates (exit 1 on problems)
soveryn doctor --self-test # assertExact self-test
npm test                  # unit tests (node --test test/)
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
- `glm` → `http://10.10.10.2:8001/v1` / `glm-5.3-flash` (park/unpark is owner-gated; `soveryn status` shows live truth, `doctor` flags parked-but-live drift and hand-edited generated configs)
- `aetheria` → `http://127.0.0.1:8090/v1` / `aetheria` (live)

Provider ids: `soveryn-flash`, `soveryn-glm`, `soveryn-aetheria`.

## Install (this machine)

```bash
ln -sfn "$HOME/soveryn_vnext/packages/soveryn-cli/bin/soveryn-pi100" "$HOME/bin/soveryn"
# rollback to the previous pin: ln -sfn "$HOME/soveryn_vnext/packages/soveryn-cli/bin/soveryn-pi099" "$HOME/bin/soveryn"
# older pin:                     ln -sfn "$HOME/soveryn_vnext/packages/soveryn-cli/bin/soveryn-pi087" "$HOME/bin/soveryn"
ln -sfn "$HOME/soveryn_vnext/packages/soveryn-cli/bin/soveryn" "$HOME/bin/soveryn-074"   # rollback runtime
# ensure ~/bin is on PATH
soveryn doctor
```

Runtime (2026-10-02): `soveryn` runs pinned **Pi 1.0.0** on **Node 22.23.2**
(`bin/soveryn-pi100`: explicit `~/.nvm/versions/node/v22.23.2/bin/node` +
`~/.soveryn/pi/1.0.0`; nvm default stays Node 20, PATH untouched; Pi 1.0.0 needs Node >=22.19).
Pin install: `PATH=~/.nvm/versions/node/v22.23.2/bin:$PATH npm install --prefix ~/.soveryn/pi/1.0.0 --ignore-scripts --save-exact @earendil-works/pi-coding-agent@1.0.0`.
Previous pin `bin/soveryn-pi099` (Pi 0.99.1, `~/.soveryn/pi/0.99.1`) stays installed as the first rollback,
`bin/soveryn-pi087` (Pi 0.87.1, `~/.soveryn/pi/0.87.1`) as the second;
version-gated settings follow `SOVERYN_PI_VERSION`, so rolling the symlink back also rolls the generated settings back.
Pi 1.0 defaults the interactive TUI to fullscreen (alt screen). The pinned runtime on Pi >=1.0.0 writes
`"tuiMode": "regular"` (`src/pinned-pi.js` `pinnedSettingsTuiMode`) so the locked C64/PETSCII look and the
terminal's normal scrollback stay as on 0.99.1; older pins omit the key (settings byte-identical).
The wrapper always passes `--model provider/model` (Pi 1.0 errors on `--provider` without `--model`).
Pi 0.99 built-ins (`builtin:mcp`, `builtin:codemode`, `builtin:tool-search`, `builtin:llama.cpp`):
the pinned runtime writes `"extensions": ["-builtin:mcp"]` (`src/pinned-pi.js` `pinnedSettingsExtensions`)
because `defaultProjectTrust: "always"` would otherwise auto-connect a project `.pi/mcp.json`.
`codemode` / `tool_search` stay loaded but their tools are off by default (only MCP turns them on);
llama.cpp stays enabled (no `--no-extensions`). Note: a project `.pi/settings.json` entry `+builtin:mcp`
still overrides the user setting (Pi behavior), same trust surface as project extensions.
`soveryn-074` = legacy Pi 0.74.2 from PATH on Node 20. Kernel (`kernel` / `soveryn-pi`)
is unaffected: `SOVERYN_HARNESS=kernel` ignores the pin (`src/pinned-pi.js`).
Pinned-runtime extras: `PI_TRUE_COLOR=1` (keeps the locked theme in truecolor),
`lastChangelogVersion` follows the runtime; `defaultProjectTrust: "always"` in
`config/soveryn-cli/settings.json` (agent-dir scoped) means no trust prompt in TUI or `-p`.
Context window: Pi >=0.80 clamps each request's `max_tokens` to `contextWindow - estimatedContext - 4096`
(floor 1). profiles.json `contextWindow` is the house working budget shared with Kernel (0.74.2 never
clamps), so the pinned runtime reads the server's real limit from `config/soveryn-cli/pinned-runtime.json`
(`serverContextWindow`: glm 1000000, flash 262144, aetheria 65536). Without it, GLM replies truncate
(`stopReason: length`, 1-300 output tokens) once context passes ~28k. Update it when a serve's limit changes.


## Option 2 chrome (dark lab)

Pre-launch splash + status HUD: large monospace **SOVERYN** wordmark, cyan/amber accents on near-black, active brain + ONLINE.

- Theme: Pi `soveryn-lab` (SSOT `packages/soveryn-cli/themes/soveryn-lab.json`; `config/*/themes/` are symlinks). `ensureLabTheme` still copies into the live agent dir on launch if the symlink is missing.
- File search: install `fd` on `PATH` (`apt install fd-find` then symlink `fdfind` → `fd`, or `brew install fd`). Do not vendor the binary.
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
