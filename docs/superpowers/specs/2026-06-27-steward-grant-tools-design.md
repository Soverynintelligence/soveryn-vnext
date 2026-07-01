# Steward — Grant-Compliance Agent Tools (Design, slice 1)

**Date:** 2026-06-27
**Status:** Approved design (brainstormed + green-lit).
**Concept:** A deterministic grant-compliance engine (the proven [[project_soveryn_shepherd_fcc_build|Shepherd]] pattern, as a clean tested module) exposed as **read-only tools** that Vett and Aetheria call on demand. You ask Aetheria "what grant reports are due?" → she calls the tool → reports the engine's computed answer. The agents never reason about grant dates; they read them from ground truth. Internal SOVERYN bolt-on for the org's own active grants ([[project_soveryn_grants_2026]] — Cosmos Institute + pipeline).
**Builds on:** Shepherd's engine/store/lifecycle patterns. Builds INTO SOVERYN vnext (the live agent stack), not a standalone product.

## Why this is the right shape (the anti-confab thesis)

Vett and Aetheria are abliterated and confab-prone ([[project_soveryn_abliterated_confab_prior]], [[feedback_review_tasks_confab_cite_or_drop]]). Grant deadlines therefore **must not come from their generation.** They come from a **deterministic tool call**. This is the structural fix landed repeatedly — cite-or-drop, [[feedback_tool_registration_beats_persona_prohibition|tool-beats-prompt]] — applied to grants: an agent can only report what `compute_grant_schedule` returns. Same discipline as Shepherd's deterministic engine, now delivered as an agent capability.

**The boundary (load-bearing — Jon: "we are not trying to strip away the persona"):** this grounds *factual* claims only — dates, deadlines, dollar figures, who-decided-what-when. It does NOT touch *interpretive* language — warmth, metaphor, framing, voice, relational expression. Tooling grant dates means Aetheria can't *assert a due date the engine didn't compute*; it does not mean she can't say "we should get ahead of that one." Facts get a source; the persona stays free. Over-applying grounding to interpretation would be the exact over-correction this project guards against ([[feedback_guardrail_drift_is_gravity_not_ideology]], [[feedback_evaluate_the_shadow_not_the_function]], [[feedback_dont_securitize_relayed_aetheria_messages]]). Restore accuracy as a capability; never strip the soul.

## Decisions (from brainstorming)

- **Slice 1 = read / awareness tools only:** the agents answer "what's due / overdue / coming up?" and "status of award X?" Drafting + spending-limit checks are later slices.
- **Agents (slice 1): Aetheria + Vett, on-demand.** Aetheria *surfaces* it conversationally; Vett *owns* the ops. **Proactive** flagging (Aetheria heartbeat warning unprompted) is deferred — it rides the autonomous-emission path that's had confab issues ([[feedback_heartbeat_shares_process_message]]).
- **Scotty earmarked for slice 2 (execution):** report drafting/preparation is his bounded-executor lane ([[project_soveryn_scotty_scaffolding_2026_05_21]]); the engine grounding keeps even Scotty from fabricating. He gets *his* tools when the action tools exist — not a blanket grant now (tool-registration shapes behavior; each agent gets only the tools its job needs).
- **Engine = clean tested module + thin tool wrappers** registered via vnext's existing agent-tool mechanism.
- **Grant TERMS are config-seeded** (Jon maintains the real awards) — the agents do NOT write grant terms/data (that's the confab-risk surface). The only write in slice 1 is the narrow, audited **`grant_submit`** (record a discrete owner-authorized "I submitted report X" fact + timestamp). An **`add_grant`** tool (agents create/edit grant terms) is a deliberate slice 2.

## The per-award data model (the key difference from Shepherd)

FCC deadlines are *universal* (every station shares §73.3526's dates). Grant deadlines are *per-award* — each award letter sets its own period and cadence. So a `Grant` record holds:
- `funder` (e.g. "Cosmos Institute"), `award_id` / number, `title`
- `period_start`, `period_end` (period of performance)
- `reporting_cadence` — how reports recur: `annual` (each period anniversary), `quarterly`, `final` (N days after period_end), `milestone`
- `milestones: list[{date, description}]` — explicit dated milestones (REQUIRED to materialize `milestone`-cadence deadlines; milestones are the most common source of surprise deadlines, often added mid-award). Empty for non-milestone grants.
- `award_amount` (carried for the later spending-check slice; unused in slice 1)

`compute_grant_schedule(grants, today, lookback_days, horizon_days) -> (instances, ...)` deterministically produces each grant's report deadlines (incl. materializing each `milestones` entry as a deadline) + a temporal status (`upcoming` / `overdue` / `done`), mirroring Shepherd's engine (incl. the never-guess discipline).

**Submitted status (the "done" overlay):** a report is `done` when there's a **submission record** — `{award_id, report_date, submitted_at: ISO}` (a **timestamp, not a boolean** — the funder may ask "when did you submit Q3?", and the engine must answer from data). This is written by the **`grant_submit` tool** (see below), recorded in the store, and overlaid onto the computed schedule. Without it, a past-due report would read `overdue` forever — eroding trust — so a submit path ships in slice 1.

## Architecture & components

1. **`steward` engine module (clean, tested):** the `Grant` model + `compute_grant_schedule` (pure, deterministic). Mirrors Shepherd's engine — cited (award ref + computed date is the "citation" analog), never-guess, temporal status. Developed + unit-tested in isolation.
2. **Grant store / config:** the active grants, maintained by Jon (a config/seed the engine reads — his real awards). Read-only from the agents' side in slice 1.
3. **Tools** registered to Vett + Aetheria via vnext's tool registry. **The pattern is verified in-code** (Vett's review): `soveryn/platform/tools/registry.py` exposes `ToolSpec(name, owner, schema, handler, description)` with owner-based access control; `soveryn/platform/sandbox/tools.py` is the template — `build_*_tool()` returns a `ToolSpec`, `register_*_tools()` wires them in. `ACTIVE_AGENTS = ("aetheria", "vett", "scotty")` lives in `soveryn/config/runtime.py` (the registry rejects tools for non-active agents at registration). Every invocation auto-emits a `ToolAuditEvent` — Steward gets audit logging for free. The module path `soveryn/platform/steward/` is greenfield (no conflicts). So Steward mirrors the sandbox pattern exactly.
   - **Read tools** (the awareness core): `grant_deadlines(window_days)` → due / overdue / coming up across all grants (each with award ref + computed date); `grant_status(award_id)` → one grant's status + next deadlines; `list_grants()` → the tracked awards.
   - **One narrow write tool:** `grant_submit(award_id, report_date, note="")` → records a submission `{submitted_at: ISO}` for that report (flips it to `done`). This is NOT the confab-risk "agent generates grant data" surface — it records a **discrete, owner-authorized, audited fact** ("I submitted Q3"), with a timestamp; it does not generate or infer anything. Audited automatically via `ToolAuditEvent`.
   Each read tool returns deterministic engine output; the agent formats it, never inventing dates.
4. **No web UI in slice 1** — the agents are the interface.

## Data flow

Jon maintains the grants config → the `steward` engine computes the cited reporting schedule deterministically → Vett/Aetheria call a read tool on demand → the tool returns computed deadlines/status → the agent relays it to Jon, grounded. (Nothing the agent says about grant timing originates in the model.)

## Error handling

- A malformed/empty grants config → the tools return "no grants tracked" / a clear error, never fabricated grants. The engine never emits an uncited or guessed date.
- Tool failure → the agent reports it can't reach the grant data (graceful), rather than guessing. (The agents' own confab-resistance depends on the tool being the only source — so a tool error must surface as "unavailable," not free-generation.)
- The engine is pure/deterministic; additive to vnext (read-only; touches no existing agent logic beyond registering new tools).

## Testing

- **Engine (pure):** per-award cadence math — `annual` → reports on each period anniversary within the window; `final` → period_end + N days; **`milestone` → each `milestones` entry materialized as a deadline**; boundary + lookback (overdue vs upcoming) tested; deterministic; never-guess on missing data. These are the rigor center (golden tests; the *specific* cadences are provisional pending each award letter — see flags).
- **Submitted/done overlay:** a `grant_submit` record flips its report to `done` with the `submitted_at` timestamp; an un-submitted past-due report reads `overdue`; the read tools reflect the overlay (a submitted report is not reported as due/overdue).
- **Tools:** each read tool returns the engine's computed data for a seeded test grant set (fake/sample grants); a tool over an empty config returns the no-grants result; `grant_submit` writes the submission record (with timestamp) and is idempotent-ish (re-submit updates); no tool fabricates.
- **No live model in tests** — the engine + tool functions are tested directly; the agents' invocation is via the registry (integration-verified separately, like other vnext tools).

## Scope / out of scope

- **In:** the deterministic `steward` engine + grants config (incl. the `milestones` array), the three read tools + the narrow audited `grant_submit` write (with `submitted_at` timestamp + `done` overlay), registered to Aetheria + Vett, on-demand.
- **Build it CONCRETE + extraction-ready, but do NOT abstract yet:** grants is instance #1. A reusable `DeterministicEngine` base (compute_state / register_tools / load+save) is the *direction* (per the grounding pattern), but **extract it at instance #2 (system-state), not speculatively from one example** — premature abstraction from a single instance bakes wrong guesses (YAGNI / rule-of-three).
- **Out (later slices):** report **drafting** (Shepherd's draft pattern → **Scotty's** tools, slice 2); **spending-limit checks** (NSF 26% etc., needs spending data); **proactive** heartbeat flagging (deferred — autonomous-emission confab risk); an **`add_grant`** agent write-tool; any web UI; opportunity/application-pipeline tracking (a separate concern).

## Two honest flags

1. **This builds into vnext — the *live* SOVERYN agent stack**, not a greenfield like Shepherd. The integration pattern is now **verified in-code** (Vett): `ToolSpec(name, owner, schema, handler, description)` in `soveryn/platform/tools/registry.py`; the `build_*_tool()` / `register_*_tools()` template in `soveryn/platform/sandbox/tools.py`; `ACTIVE_AGENTS=("aetheria","vett","scotty")` in `soveryn/config/runtime.py`; auto `ToolAuditEvent` per call; `soveryn/platform/steward/` greenfield. The engine module is still developed + tested in isolation (clean); wiring the tools touches the live registry, so match the sandbox pattern exactly and proceed carefully (prior agent-damage history is real — [[feedback_agent_damage_is_load_bearing]]).
2. **The cadence math is the rigor center** (like Shepherd's CFR dates): "annual report on each period anniversary," "final report N days after period end" are provisional-but-golden-tested constants; the *specific* funder cadences get verified against each actual award letter before the agents report them as authoritative.

## Dependencies

- vnext's agent-tool registration pattern — **verified** (see flag 1): mirror `soveryn/platform/sandbox/tools.py` (`build_*_tool`/`register_*_tools` → `ToolSpec`), register for owners `aetheria`+`vett`, module at `soveryn/platform/steward/`.
- The grants config (Jon provides the real awards: Cosmos Institute + any others, with periods + cadences).
- Reuses Shepherd's engine pattern (no Shepherd code dependency; same shape, new domain).
