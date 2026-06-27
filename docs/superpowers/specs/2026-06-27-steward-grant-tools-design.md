# Steward — Grant-Compliance Agent Tools (Design, slice 1)

**Date:** 2026-06-27
**Status:** Approved design (brainstormed + green-lit).
**Concept:** A deterministic grant-compliance engine (the proven [[project_soveryn_shepherd_fcc_build|Shepherd]] pattern, as a clean tested module) exposed as **read-only tools** that Vett and Aetheria call on demand. You ask Aetheria "what grant reports are due?" → she calls the tool → reports the engine's computed answer. The agents never reason about grant dates; they read them from ground truth. Internal SOVERYN bolt-on for the org's own active grants ([[project_soveryn_grants_2026]] — Cosmos Institute + pipeline).
**Builds on:** Shepherd's engine/store/lifecycle patterns. Builds INTO SOVERYN vnext (the live agent stack), not a standalone product.

## Why this is the right shape (the anti-confab thesis)

Vett and Aetheria are abliterated and confab-prone ([[project_soveryn_abliterated_confab_prior]], [[feedback_review_tasks_confab_cite_or_drop]]). Grant deadlines therefore **must not come from their generation.** They come from a **deterministic tool call**. This is the structural fix landed repeatedly — cite-or-drop, [[feedback_tool_registration_beats_persona_prohibition|tool-beats-prompt]] — applied to grants: an agent can only report what `compute_grant_schedule` returns. Same discipline as Shepherd's deterministic engine, now delivered as an agent capability.

## Decisions (from brainstorming)

- **Slice 1 = read / awareness tools only:** the agents answer "what's due / overdue / coming up?" and "status of award X?" Drafting + spending-limit checks are later slices.
- **Agents (slice 1): Aetheria + Vett, on-demand.** Aetheria *surfaces* it conversationally; Vett *owns* the ops. **Proactive** flagging (Aetheria heartbeat warning unprompted) is deferred — it rides the autonomous-emission path that's had confab issues ([[feedback_heartbeat_shares_process_message]]).
- **Scotty earmarked for slice 2 (execution):** report drafting/preparation is his bounded-executor lane ([[project_soveryn_scotty_scaffolding_2026_05_21]]); the engine grounding keeps even Scotty from fabricating. He gets *his* tools when the action tools exist — not a blanket grant now (tool-registration shapes behavior; each agent gets only the tools its job needs).
- **Engine = clean tested module + thin tool wrappers** registered via vnext's existing agent-tool mechanism.
- **Grants are config-seeded** (Jon maintains the real awards) — NOT an agent write-tool in slice 1 (keeps agent tools strictly read-only; no agent-writes-the-source-of-truth surface). An `add_grant` tool is a deliberate slice 2.

## The per-award data model (the key difference from Shepherd)

FCC deadlines are *universal* (every station shares §73.3526's dates). Grant deadlines are *per-award* — each award letter sets its own period and cadence. So a `Grant` record holds:
- `funder` (e.g. "Cosmos Institute"), `award_id` / number, `title`
- `period_start`, `period_end` (period of performance)
- `reporting_cadence` — how reports recur: `annual` (each period anniversary), `quarterly`, `final` (N days after period_end), `milestone` (explicit dated milestones)
- `award_amount` (carried for the later spending-check slice; unused in slice 1)

`compute_grant_schedule(grants, today, lookback_days, horizon_days) -> (instances, ...)` deterministically produces each grant's report deadlines + a temporal status (`upcoming` / `overdue`), mirroring Shepherd's engine (incl. the never-guess discipline). "Done/submitted" needs a filed-overlay — for slice 1, a simple per-report `submitted` mark in the config/store is enough; the full mark-as-filed flow is later.

## Architecture & components

1. **`steward` engine module (clean, tested):** the `Grant` model + `compute_grant_schedule` (pure, deterministic). Mirrors Shepherd's engine — cited (award ref + computed date is the "citation" analog), never-guess, temporal status. Developed + unit-tested in isolation.
2. **Grant store / config:** the active grants, maintained by Jon (a config/seed the engine reads — his real awards). Read-only from the agents' side in slice 1.
3. **Read-only tools** (registered to Vett + Aetheria via vnext's existing tool registry — the build must first locate + match the pattern Vett/Aetheria's current tools use):
   - `grant_deadlines(window_days)` → reports due / overdue / coming up across all grants (each with award ref + computed date).
   - `grant_status(award_id)` → one grant's status + its next deadlines.
   - `list_grants()` → the tracked awards.
   Each returns deterministic engine output; the agent formats it for Jon, never inventing dates.
4. **No web UI in slice 1** — the agents are the interface.

## Data flow

Jon maintains the grants config → the `steward` engine computes the cited reporting schedule deterministically → Vett/Aetheria call a read tool on demand → the tool returns computed deadlines/status → the agent relays it to Jon, grounded. (Nothing the agent says about grant timing originates in the model.)

## Error handling

- A malformed/empty grants config → the tools return "no grants tracked" / a clear error, never fabricated grants. The engine never emits an uncited or guessed date.
- Tool failure → the agent reports it can't reach the grant data (graceful), rather than guessing. (The agents' own confab-resistance depends on the tool being the only source — so a tool error must surface as "unavailable," not free-generation.)
- The engine is pure/deterministic; additive to vnext (read-only; touches no existing agent logic beyond registering new tools).

## Testing

- **Engine (pure):** per-award cadence math — `annual` → reports on each period anniversary within the window; `final` → period_end + N days; boundary + lookback (overdue vs upcoming) tested; deterministic; never-guess on missing data. These are the rigor center (golden tests; the *specific* cadences are provisional pending each award letter — see flags).
- **Tools:** each tool returns the engine's computed data for a seeded test grant set (fake/sample grants); a tool over an empty config returns the no-grants result; no tool fabricates.
- **No live model in tests** — the engine + tool functions are tested directly; the agents' invocation is via the registry (integration-verified separately, like other vnext tools).

## Scope / out of scope

- **In:** the deterministic `steward` engine + grants config, the three read-only tools, registered to Aetheria + Vett, on-demand.
- **Out (later slices):** report **drafting** (Shepherd's draft pattern → **Scotty's** tools, slice 2); **spending-limit checks** (NSF 26% etc., needs spending data); **proactive** heartbeat flagging (deferred — autonomous-emission confab risk); an **`add_grant`** agent write-tool; any web UI; opportunity/application-pipeline tracking (a separate concern).

## Two honest flags

1. **This builds into vnext — the *live* SOVERYN agent stack**, not a greenfield like Shepherd. The engine module is developed + tested in isolation (clean), but wiring the tools means touching the live agent registry, so the build **first locates how Vett/Aetheria's existing tools are registered and matches that pattern**, carefully (prior agent-damage history is real — [[feedback_agent_damage_is_load_bearing]]).
2. **The cadence math is the rigor center** (like Shepherd's CFR dates): "annual report on each period anniversary," "final report N days after period end" are provisional-but-golden-tested constants; the *specific* funder cadences get verified against each actual award letter before the agents report them as authoritative.

## Dependencies

- vnext's agent-tool registration pattern (locate + follow it).
- The grants config (Jon provides the real awards: Cosmos Institute + any others, with periods + cadences).
- Reuses Shepherd's engine pattern (no Shepherd code dependency; same shape, new domain).
