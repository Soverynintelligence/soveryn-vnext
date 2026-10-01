# SOVERYN CLI — failure-mode hardening (2026-09-09)

Parallel path only (`config/soveryn-cli`, `packages/soveryn-cli`). Kernel / `config/pi` untouched.

## Problems Jon reported

1. **Agent burns tries/retries without real work** — identical failed tool calls, empty planning loops, progress claims without tool results.
2. **Compaction-caused looping** — seen on OpenCode (aggressive context pressure / prune). Same class on Pi: auto-compact mid-tool-loop with a small keep-recent window → amnesia → re-do the same tools → compact again.

## Pi 0.74.2 compaction semantics (installed `@earendil-works/pi-coding-agent`)

Triggers when:

```
contextTokens > contextWindow - reserveTokens
```

Defaults in Pi: `reserveTokens=16384`, `keepRecentTokens=20000`.
After cut, only ~`keepRecentTokens` recent messages stay verbatim; older span becomes a lossy summary. A single huge tool turn that exceeds keep-recent becomes a **split turn** (mid-loop cut) — high loop risk.

OpenCode reference (read-only): house `config/opencode/opencode.json` exposes a **131072** context limit for Flash coding (half of real 256k) with **no** explicit compaction knobs — vendor prune/overflow behavior was the loop class to avoid on Pi.

## Chosen Flash-Next (256k) values

| Key | Value | Why |
|---|---|---|
| `compaction.enabled` | `true` | Long coding sessions still need an escape hatch before hard overflow |
| `reserveTokens` | `18432` | ≈ `maxTokens` (16k) + 2k; fires late (~93% of 262144 → trigger above ~243712) |
| `keepRecentTokens` | `65536` | Keep ~64k recent so multi-tool turns rarely split; reduces compact-chase |

GLM / Aetheria profiles keep **`compaction.enabled: false`** (32k windows — compact would be aggressive and lossy).

Previous Flash values (`reserveTokens=20480`, `keepRecentTokens=20000`) fired slightly earlier and kept too little after compact for tool-heavy turns.

## Prompt anti-patterns (`SYSTEM.md` / `AGENTS.md`)

- No identical failed tool retries
- Stop after 3 failed attempts on the same goal; report blocker
- No compact-chase / full-tree re-read after summary
- Prefer one concrete edit over empty planning
- Never claim progress without a tool result

## Doctor warnings

`soveryn doctor` / `status` flags dangerous compaction shapes (too-small keep-recent on large windows, reserve above ~15% of context, reserve below maxTokens).

## Retry settings

Left at Pi defaults (`retry.maxRetries=3`, provider `maxRetries=0`). Those cover **transient API** errors, not tool-call anti-patterns (handled in prompts).

## Policy gates (2026-09-09) — native, not prose-only

Kernel RESEARCH §4 named four harness gates. Parallel soveryn-cli now enforces them in
`packages/soveryn-cli/src/policy/` (see `POLICY-GATES.md`):

1. Verification not blind — doctor dual-signals (modules + sinks + timeout wiring)
2. Tests cannot defang — `assertExact` code-point compare (`doctor --self-test`)
3. Sink hardening → callers audit — `policy/sinks.json` + doctor
4. Canonical names — profile/provider/model id normalisation + boot assert
5. Bounded `-p` — `limits.maxPrintSeconds` default 120 / `SOVERYN_PRINT_TIMEOUT_MS`

```bash
~/bin/soveryn doctor --gates
~/bin/soveryn doctor --self-test
```
