# Borrowed from DeepSeek Harness (dsh) — what we took / deferred

**Date:** 2026-09-10 (ET)  
**Constraint:** Do **not** install `@deepseek-ai/dsh` here. It needs **Node ≥ 22**; Soveryn tower is **Node 20**. dsh Web-UI also fights the locked C64 / soveryn-lab TUI — keep Pi chrome alone.

Research source: [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) (Cordis compositions, agent presets, Code Mode / `run_code`).

---

## Implemented (practical now)

| Idea | dsh shape | SOVERYN / Pi shape |
|---|---|---|
| **Presets (minimal vs full tools)** | Agent presets + tool rows / restrict | `profiles.json` `defaultPreset` + per-profile `preset`; CLI `--preset minimal\|standard`, `--minimal`, `--standard` → Pi `0.74.2` `--tools bash,edit` (minimal) or default full built-ins (standard). See `packages/soveryn-cli/src/presets.js`. |
| **Plugin-shaped policy layer** | Cordis “services” / plugin rows | **Documented mapping only** onto existing `packages/soveryn-cli/src/policy/*` + chrome (below). No Cordis runtime. |
| **Code mode (spirit)** | `tools.mode: code` + `run_code` + generated SDK | Guidance in `SOVERYN.md` + session append via `--code-mode` → Pi `--append-system-prompt` `packages/soveryn-cli/prompts/CODE-MODE.append.md`. Prefer one coherent edit/script pass over micro round-trips. |
| **AGENTS.md compatibility** | Agent context files | **Already done:** `config/pi/AGENTS.md` → `SOVERYN.md`, `config/soveryn-cli/AGENTS.md` → `../pi/SOVERYN.md`, repo root `SOVERYN.md` → `config/pi/SOVERYN.md`. Pi loads AGENTS.md. |
| **OpenAI-compat custom provider** | dsh custom OpenAI-compatible endpoint | **Already have** Flash-Next / GLM / Aetheria as Pi `openai-completions` providers in `models.json` (from profiles). Same house endpoints. After Node 22, dsh could point at the same `:8888` / `:8001` / `:8090` URLs — not installed here. |

### Cordis-like “services” → existing SOVERYN modules

| Cordis-ish concern | SOVERYN file / surface |
|---|---|
| Policy / allow-deny gates | `src/policy/gates.js` + `POLICY-GATES.md` |
| Exact assert / anti-defang | `src/policy/assert.js` |
| Sink registry + caller audit | `src/policy/sinks.json`, `sinks.md` |
| Bounded exec / limits | `src/policy/limits.js`, `profiles.json` `limits` |
| Canonical names | `src/policy/canonical.js` |
| Chrome / TUI brand | `src/chrome.js`, theme `soveryn-lab` (**C64 locked — do not revert**) |
| Launch / tool presentation | `src/launch.js` + `src/presets.js` (Pi `--tools`, `--append-system-prompt`) |

Enforcement stays in code (`soveryn doctor --gates`); this file is the borrow ledger.

---

## Deferred (not now)

| Item | Why deferred |
|---|---|
| Install `@deepseek-ai/dsh` | Node ≥ 22; tower is Node 20 |
| Full Cordis composition / plugin host | Would replace or fight Pi harness; policy already native |
| dsh Code Mode runtime (`run_code`, worker-thread / SDK) | Needs dsh + Node 22; also sandbox-escape caveats upstream — we only borrowed the *anti-roundtrip* spirit |
| dsh Web-UI | Conflicts with locked C64 / soveryn-lab TUI |
| Pointing dsh at Flash-Next after Node 22 | Same OpenAI-compat endpoints ready; wait for Node upgrade |

---

## Later: owner trial (queued 2026-09-11)

Jon: dsh is **worth a test**. Public results look strong. Save for later — **do not install now**, **do not replace Kernel / Pi**.

Agreed shape when we pick this up:

1. Isolated home + workspace (not `~/.dsh` on the live Kernel tree). Suggested: `~/soveryn-harness/dsh-trial/` + a disposable sandbox.
2. **Node 22 sidecar** — do not upgrade tower Node 20. Do not `npx @deepseek-ai/dsh` on Node 20.
3. Point at **Flash-Next** `http://127.0.0.1:8888/v1` (OpenAI-compat already in `models.json`). Optional: GLM `:8001` / Aetheria `:8090` if parked/unparked.
4. Headless or `--no-open` first. Web UI `:3080` only in a sandbox; **never** swap Kernel’s C64 / soveryn-lab TUI.
5. Score against the Kernel drain we already know: stale-session resume, compaction amnesia, loop guard, bash-vs-open-html, thinking default. One short coding task + one long session — not a chassis swap.
6. Kernel stays Pi until Jon says otherwise.

Pickup phrase: “run the dsh trial” / “the DeepSeek Harness later.”

---

## JIT-steal harness (ran 2026-09-12) — not dsh

Lab only: `~/ablit-bake/jit-exp/` against stock Flash-Next `:8888`. Production `opencode.json` and Pi **untouched**. Write-up: `REPORT.md`, `results.json`, **Jon’s calls in `DECISIONS.md`**.

| Exp | Result | Decision |
|---|---|---|
| 1 phase allowlists (deny webfetch + curl/wget) | PARTIAL. curl ok 7→1; model bypassed with python urllib; completions 9→7; webfetch tool never registered | **Do not promote.** Next overlay must stop bash net, then re-run. |
| 2 2-strike bash retry (`JIT_TOOL_RETRY=1`, default off) | PASS mechanism. 4 retries; flaky-once recovered in one call. Completions not improved on 5-task set | **Keep as env-gated overlay.** Do not patch Pi until Jon says. |

`opencode run` hangs without a PTY (`script -q -c`). ABLIT left OFF (stock restored).

---

## Commands (new flags)

```bash
soveryn --minimal                 # --tools bash,edit
soveryn --standard                # full defaults (explicit)
soveryn --preset minimal|standard
soveryn --code-mode               # append CODE-MODE.append.md
kernel --minimal | --code-mode    # same CLI via soveryn-pi
```

Passthrough still wins: `soveryn -- --tools read,bash,edit,write …`.

Verify: `soveryn status`, `soveryn -p "ping"`, `soveryn doctor --gates`.
