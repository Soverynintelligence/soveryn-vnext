# SOVERYN CLI · policy gates (native controls)

**Enforcement is in code** (`packages/soveryn-cli/src/policy/`), not in this prose file.
Doctor surfaces gate status; optional launch preflight warns (or refuses if
`SOVERYN_GATES_STRICT=1`).

## Credit

The four gates and fuse analysis originated in **Kernel**'s harness research:
`~/soveryn-harness/RESEARCH.md` §4 (2026-09-09). This document implements those
gates as the SOVERYN policy layer around Pi — it does **not** rewrite Pi's agent
loop.

## How to run

```bash
~/bin/soveryn doctor            # status + all gates (exit 1 on FAIL)
~/bin/soveryn doctor --gates    # gates only
~/bin/soveryn doctor --self-test  # assertExact must reject mismatches
```

## The four gates (+ bounded print)

| ID | Gate | Native control |
|---|---|---|
| `G1_VERIFICATION_NOT_BLIND` | Verification must not be blind | Dual signals: policy modules on disk **and** sinks seed exact match **and** print-timeout wiring in `launch.js`. Print-mode self-check alone is not proof. |
| `G2_TEST_NOT_DEFANG` | A test must not defang itself | `assertExact(actual, expected)` — Unicode **code-point** comparison. Truncation / single-char corruption must throw `ASSERT_EXACT`. |
| `G3_SINK_CALLERS_AUDITED` | Hardening a sink obliges auditing callers | `src/policy/sinks.json` + `sinks.md`; doctor fails unless every sink has `callers_audited: true` and the file exists. Seed: spawn/pi launch, profile write, curl health. |
| `G4_CANONICAL_NAMES` | Single-char / case corruption is first-class | `canonicalizeId` for profile/provider ids; boot assert over critical names (`flash`, `glm`, `aetheria`, `qwen3.8-flash-next`, `soveryn-flash`, …). |
| `G5_BOUNDED_PRINT` | Bounded execution (from prose → control) | `limits.maxPrintSeconds` (default **120**) / env `SOVERYN_PRINT_TIMEOUT_MS`; `-p` spawn killed on exceed (exit 124). |
| `G6_TOOL_EVIDENCE` | Progress claims need tool evidence | `harness-controls` JSONL sidecar + claim annotation; doctor executes append/read. Loop-guard env is validated (`parseLoopLimit`): NaN/0/Infinity cannot silently disable. |
| `G7_API_SURFACE` | Browser APIs probed, not invented | Live Chromium `web-api-probe`; doctor executes probe. WARN if Chrome missing. `html-module-host --self-test` proves `%2e%2e` cannot escape `--dir`. |
| `G8_OUTPUT_FIDELITY` | Generation integrity (length + code points) | `policy/fidelity.js` — corruption battery (`matchAllAll`, `upppercase`, `@@keyframes`, `config/ppi`); deliberate fail in `--self-test`. |

## Config

- `config/soveryn-cli/profiles.json` → `"limits": { "maxPrintSeconds": 120 }`
- Env: `SOVERYN_PRINT_TIMEOUT_MS` (milliseconds, wins over config)
- Env: `SOVERYN_GATES_STRICT=1` — refuse launch on gate FAIL

### Showme / loop guard

- `soveryn --showme` / `SOVERYN_SHOWME=1` — visual done needs screenshot/`file://` (`open-html`).
- Loop guard blocks 3rd identical failed tool call (`SOVERYN_LOOP_GUARD`, default 3). Soft-fails (`DT_FAIL`, `verdict=*FAIL`, `Error:`, traceback, TIMEOUT) count even when the tool returns OK. Chrome bash fingerprints by dump kind + `.html` target.
- Packs: `config/soveryn-cli/TOOL-PACKS.md`.

## Residual gaps (need Pi extension hooks later)

Partially closed by `harness-controls` + web pack (evidence sidecar, loop guard, API probe, showme annotations).
Still residual / deeper Pi hooks:

- Hard **reject** (not annotate) of assistant progress claims at the provider API boundary
- Tool-runtime bounded exec for **every** bash spawn inside Pi (beyond Chrome 20s wrapper + CLI `-p`)
- ActTruth ledger as first-class native tool events in Command Center
- Blind-verification pairs for rAF vs setTimeout animation pumps
- Permission gates (`rm -rf`, sudo, `.env`, force-push) routed to Messages
- Edit-gate + path protection inside Pi hooks

See Kernel RESEARCH §4–§6 for the full fuse plan.

## Cordis / dsh mapping (borrow ledger)

DeepSeek Harness Cordis “services” are **not** installed. The mapping of policy /
limits / sinks / chrome onto this tree is recorded in
`config/soveryn-cli/BORROWED-FROM-DEEPSEEK.md` (presets + code-mode spirit only;
Node 22 / full Cordis / `run_code` deferred).

