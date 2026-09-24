# SOVERYN CLI Harness — Full Build Spec

**Status:** Draft for Jon / SOVERYN Intelligence  
**Date:** 2026-09-09  
**Codename:** `soveryn` (CLI product name) · day-to-day alias `kernel`  
**Agent core:** Pi Coding Agent `0.74.2` (wrap, do not fork)  
**Not in scope as primary:** OpenCode (known issues), Claude Code, Codex, Kimi, Antigravity, Amp

---

## 1. Problem

Today Kernel coding is usable but not *branded* or *switchable*:

- Live path is Pi via `kernel` → `soveryn-pi` → Flash-Next (`qwen3.8-flash-next` @ `http://127.0.0.1:8888/v1`).
- Provider id is still misleadingly named `kernel-glm` while serving Flash-Next.
- `--glm` is a **stub** (same as `--flash`); real GLM lives only in bak files (`:8001`, `glm-5.3-flash`).
- House brain switch (`switch_kernel_brain.sh` + `~/.soveryn/kernel_brain`) does **not** drive Pi models.
- Switching Flash-Next ↔ GLM ↔ Aetheria requires editing configs or remembering flags; no picker / “button”.
- Thinking / context / compaction settings differ per brain and are easy to get wrong on switch.

**Goal:** One branded SOVERYN CLI harness where models are **profiles**, and switching is as easy as picking a row (TUI) or one flag / subcommand — including GLM when that lane is live again.

---

## 2. Product principles

1. **Own the edges, reuse the loop** — SOVERYN owns branding, profiles, switcher, health, docs. Pi owns tools/agent loop until Node allows a deliberate Pi upgrade.
2. **Profiles, not raw URLs** — Users pick `flash`, `glm`, `aetheria`, never hunt ports.
3. **One command family** — `soveryn …` is the product; `kernel` remains a thin forever-alias.
4. **Safe defaults** — thinking **off** for Flash-Next; per-profile overrides documented.
5. **Honest availability** — if GLM is parked, the switcher shows it disabled with why, not a silent no-op.
6. **No vendor CLI lock-in** — OpenAI-compatible baseURLs only; lab LAN first.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────┐
│  soveryn / kernel  (branded CLI — Node or Bash+TUI)     │
│  · model picker  · profiles  · health  · banners        │
└───────────────────────────┬─────────────────────────────┘
                            │ exec
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Pi 0.74.2  (--offline, PI_CODING_AGENT_DIR=…)          │
│  tools · sessions · AGENTS.md · SYSTEM.md               │
└───────────────────────────┬─────────────────────────────┘
                            │ OpenAI-compat
                            ▼
┌─────────────────────────────────────────────────────────┐
│  Lab endpoints (per profile)                            │
│  flash → 127.0.0.1:8888/v1  (tunnel → spark2)           │
│  glm   → (when live) parked was 10.10.10.2:8001/v1      │
│  aetheria → 127.0.0.1:8090/v1                            │
└─────────────────────────────────────────────────────────┘
```

**Optional later:** LiteLLM / thin gateway for aliases + failover. **v1 does not require it** — profiles map straight to endpoints (same as today).

---

## 4. Model profiles (SSOT)

Single file: `config/soveryn/profiles.json` (or keep under `config/pi/` and generate `models.json`).

| Profile id | Display name | Endpoint | Model id | Status (2026-09-09) | Thinking default | Context notes |
|---|---|---|---|---|---|---|
| `flash` | Flash-Next | `http://127.0.0.1:8888/v1` | `qwen3.8-flash-next` | **live** | off | 256k; compaction on |
| `glm` | GLM 5.3 Flash | `http://10.10.10.2:8001/v1` (historical) | `glm-5.3-flash` | **parked** | low/medium per bak | 32k; compaction off |
| `aetheria` | Aetheria | `http://127.0.0.1:8090/v1` | `aetheria` | live (opt-in) | off / n/a | 32k |

Each profile also stores:

- `piProviderId` — clean names: `soveryn-flash`, `soveryn-glm`, `soveryn-aetheria` (retire `kernel-glm` as Flash)
- `healthPath` — `/v1/models`
- `enabled` — false when parked
- `disabledReason` — e.g. “GLM :8001 parked — ask Lab to reseat”
- `extraBody` — e.g. Flash `enable_thinking: false`
- `thinkingLevelMap` — per-brain
- `compaction` — on/off + reserves

**Active profile** persisted at `~/.soveryn/active_profile` (or reuse/extend `~/.soveryn/kernel_brain` with a migration: `flashnext` → `flash`).

---

## 5. CLI surface (branded)

### 5.1 Entry points

| Command | Meaning |
|---|---|
| `soveryn` | Product CLI (new) |
| `soveryn code` / `soveryn` with no subcommand | Launch Pi TUI with active profile |
| `kernel` | Alias → `soveryn code` (keep muscle memory) |

### 5.2 Model switching (“the button”)

Three equal ways — all must work:

1. **Interactive picker (primary “button”)**  
   `soveryn model` or `soveryn models`  
   - TUI list (gum / fzf / ink / blessed — pick one small dep)  
   - Arrow keys + Enter, or number keys  
   - Shows: name, status (live/parked), latency if probed  
   - Selecting a **live** profile writes active profile + regenerates Pi `models.json`/`settings.json` defaults + optional health check  
   - Selecting **parked** refuses with clear message (no silent `--glm` stub)

2. **One-shot flags** (compat + scripts)  
   - `soveryn --flash` / `soveryn code --flash`  
   - `soveryn --glm` → **real** GLM profile when enabled; error if parked  
   - `soveryn --qwen` / `--aetheria`  
   - Prefer long names: `--profile flash|glm|aetheria`

3. **Subcommand**  
   - `soveryn use flash`  
   - `soveryn use glm`  
   - `soveryn status` → active profile, endpoint, health, Pi version

### 5.3 Session launch

```
soveryn                  # TUI, active profile, thinking from profile
soveryn /path/to/repo    # cd then TUI
soveryn -p "mend X"      # Pi print mode passthrough
soveryn code --high      # thinking high for this run
soveryn code --build     # thinking off (explicit)
```

Passthrough: any unknown args after `--` go to Pi (`--session`, `--list-models`, etc.).

### 5.4 Branding in-session

- `SYSTEM.md` / `AGENTS.md` under SOVERYN config dir: SOVERYN voice, lab rules, Antigravity forbidden, Node/Pi pin note.
- Startup banner: `SOVERYN · flash · qwen3.8-flash-next · :8888 · thinking off`
- Never claim GLM if Flash is active.

---

## 6. Implementation plan (phased)

### Phase 0 — Spec lock (this doc)
- Agree profile names, picker UX, keep `kernel` alias.
- Confirm GLM remains parked until Lab reseats (switcher shows disabled).

### Phase 1 — Profile SSOT + real `--glm` semantics (1–2 days)
1. Add `config/soveryn/profiles.json` (or `config/pi/profiles.json`).
2. Rewrite `soveryn-pi` → thin dispatcher **or** new `scripts/soveryn` that:
   - Loads profiles
   - Resolves active profile
   - Generates/updates Pi provider entries with **non-colliding** ids (`soveryn-flash`, …)
   - Implements real `--glm` / `--flash` / `--aetheria`
   - Refuses parked profiles loudly
3. Migrate `defaultProvider` off legacy `kernel-glm` name.
4. Sync `~/.soveryn/active_profile` with optional bridge to `kernel_brain` for house services.
5. Update `CURRENT_TRUTH.md` + kill stale ALWAYS_ON map Kernel-on-GLM claims.

**Exit criteria:** `soveryn use flash` and `soveryn --flash` both land on `:8888`; `soveryn --glm` prints parked reason (not Flash).

### Phase 2 — Picker UX (2–3 days)
1. `soveryn model` interactive menu (recommend **gum** or **fzf** if already on box; else small Node ink TUI to stay in Node 20).
2. Probe `/v1/models` per enabled profile (timeout ~1s); show ✓/✗.
3. Persist choice; next `kernel` launch uses it with no flags.
4. Optional: in-Pi note in SYSTEM.md “run `soveryn model` to switch brains”.

**Exit criteria:** Switch Flash → Aetheria with Enter key only; relaunch shows new banner.

### Phase 3 — GLM live path (when Lab unparks)
1. Lab enables `:8001` (or new URL); flip profile `enabled: true`.
2. Apply GLM thinking map + compaction from bak.
3. Smoke: chat + tools; then `soveryn use glm` one-Enter switch.
4. Document failover (none today — call that out).

### Phase 4 — Product polish (week+)
- `soveryn status` / `soveryn doctor` (tunnel unit, ports, Pi pin, Node version).
- Completions (bash/zsh).
- Package layout: `packages/soveryn-cli` under `soveryn_vnext` with install symlink to `~/bin/soveryn`.
- Optional gateway later (LiteLLM) **behind** the same profile ids — zero UX change.
- Evaluate Pi bump only after Node ≥22.

---

## 7. Package layout (proposed)

```
soveryn_vnext/
  packages/soveryn-cli/          # NEW product
    package.json                 # name: soveryn, bin: soveryn
    src/
      cli.ts                     # commander/yargs
      profiles.ts                # load/validate profiles
      picker.ts                  # interactive switcher
      launch.ts                  # exec pi with env
      health.ts                  # /v1/models probe
    README.md
  config/soveryn/
    profiles.json                # SSOT
  config/pi/                     # generated or synced providers for Pi
    models.json
    settings.json
    SYSTEM.md
    AGENTS.md
  scripts/
    soveryn-pi                   # legacy → delegates to soveryn code
  docs/
    SOVERYN-CLI-HARNESS-SPEC.md  # this spec
```

`~/bin/soveryn` → package bin  
`~/bin/kernel` → `soveryn code`

Keep Pi at npm global `0.74.2`; CLI depends on `pi` on PATH.

---

## 8. Non-goals (v1)

- Forking Pi or bumping past 0.74.2
- Replacing Pi with OpenCode as default
- Installing Claude/Codex/Kimi/Antigravity
- Automatic GLM reseat (Lab owns serve)
- Multi-agent orchestration / cloud billing
- GUI Electron app (CLI + TUI picker only)

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| Legacy `kernel-glm` name confusion | Rename providers in Phase 1; migrate settings once |
| `--glm` stub muscle memory | Loud error + picker disabled state until live |
| House `switch_kernel_brain` vs Pi drift | Single `active_profile`; brain script calls same writer |
| GLM tools/thinking differ | Per-profile maps; doctor warns on mismatch |
| Node 20 / Pi pin | Document; no upgrade in harness project |
| OpenCode configs diverge | Leave OpenCode alone; SSOT is SOVERYN CLI + Pi dir |

---

## 10. Success criteria

- [ ] `kernel` launches branded SOVERYN banner with active profile
- [ ] `soveryn model` picker switches profiles with Enter (“button”)
- [ ] `soveryn use glm` works when GLM live; clear failure when parked
- [ ] No silent stub: `--glm` never means Flash
- [ ] Flash default thinking off; profile-specific thinking preserved
- [ ] Docs (`CURRENT_TRUTH`) match live endpoints
- [ ] Zero new vendor CLIs; Pi remains the agent loop

---

## 11. Immediate next build step (when approved)

**Phase 1 only:** profiles.json + rewrite launcher so `--glm`/`--flash`/`--aetheria`/`soveryn use` are real; picker can follow in Phase 2.

---

## Appendix — Current friction (inventory 2026-09-09)

- Launcher: `~/bin/kernel` → `soveryn-pi`
- Flash live: `127.0.0.1:8888` / `qwen3.8-flash-next`
- `--glm` currently identical to `--flash`
- GLM bak: `http://10.10.10.2:8001/v1` / `glm-5.3-flash`
- Aetheria: `--qwen` → `:8090` / `aetheria`
- Brain file `~/.soveryn/kernel_brain` not wired to Pi models.json
