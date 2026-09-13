# SOVERYN CLI · sink callers audit (Gate 3)

**Enforcement is in code** (`src/policy/sinks.json` + `soveryn doctor --gates`).
This file is the human checklist. When you harden a sink (path/open/exec wrappers,
spawn, profile write, health curl), enumerate callers in the **same change** and
set `callers_audited: true` in `sinks.json`.

Machine-readable registry: `sinks.json` (doctor fails if any entry lacks
`callers_audited: true` or the sink file is missing).

## Seed sinks (2026-09-09)

| id | file | symbol | callers |
|---|---|---|---|
| `spawn_pi_launch` | `src/launch.js` | `launchPi` / `spawn` | `cli.js` → `cmdCode` |
| `profile_write` | `src/profiles.js` | `writeActiveId` / `generatePiConfig` | `cli.js` `cmdUse`/`cmdModel`; `launch.js` |
| `curl_health` | `src/launch.js` | `spawnSync(curl)` | launch preflight; `health.js` `probe` parallel |

## Rule

Hardening a sink **obliges** auditing its callers. Do not mark audited without
listing callers. New sinks → add a row here **and** in `sinks.json` in the same PR.
