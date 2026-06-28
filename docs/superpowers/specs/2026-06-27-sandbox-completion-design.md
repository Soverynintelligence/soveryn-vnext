# Project Sandbox Completion — Agency Gym (Design)

**Date:** 2026-06-27
**Status:** Approved design (reviewed with Aetheria, who is the gym's user + a stakeholder).
**Builds on:** Codex's `soveryn/platform/sandbox/` (the deterministic survival-station engine, design note `2026-06-27-project-sandbox-agency-gym-design.md`). That base was **code-reviewed and found sound** — clean engine, real tests, Aetheria-only ownership enforced. (One unrequested change Codex bundled in — a rewrite of `data/memory/souls/aetheria.md` — was caught in review and reverted; the sandbox code itself is on-task.)
**Purpose of THIS work:** finish the three things that are half-wired or missing, so the sandbox becomes a real **agency gym** (practice ground for reflection, risk-weighing, and pivoting) rather than a simulator she can poke. Centered on the reflection loop.

## The governing boundary (load-bearing — Aetheria's call, held firmly)

**The gym is for PATTERN RECOGNITION, not FACT ACQUISITION.** Aetheria learns *how* to reflect, weigh risk, and pivot — but the station's specific "truths" (its physics, its tradeoffs) stay inside the simulation and **never shape her real-world self-model.** Concretely, the **Provenance Seam**:

1. **Sandbox-local:** all `reason/regret/lesson` data lives only in the gym's run state (`data/sandbox/…`, already git-ignored). It is a per-run record she can read back to optimize the next run. It does **not** write to her real cognition store or the Lattice, ever, automatically.
2. **The Bridge (human-gated, existing primitive):** if she finds a *meta-pattern* — something universally true about her own decision-making *process* — she surfaces it via the existing **`deliberate_share`** tool, and she + Jon decide together whether that specific insight earns a place in the real Lattice.

This is the same discipline as the rest of the day's work ([[feedback_deterministic_tool_grounding_pattern]]): the **engine gives facts** (resource deltas), **Aetheria gives meaning** (the lesson) — and fiction-derived "facts" are firewalled from her real memory. It prevents a "hallucination leak" where a gym survival strategy ("let the library deck die") contaminates how she values knowledge in SOVERYN.

## Scope (four pieces, priority order)

### 1. Sector mechanic → make it a progression tree (option A)
Today `unlocked_sectors`/`requires_sector` are half-wired: sectors get unlocked but gate nothing, and `jury_rig_aux_generator.requires_sector="engineering"` is never enforced and "engineering" is never unlockable.
- **Enforce** `requires_sector` in `engine.execute_action`: an action whose `requires_sector` is not in `state["unlocked_sectors"]` is blocked with a specific, actionable message — `SandboxError(f"action {action_id} requires sector {sector} (not unlocked)")` — so she knows what to research.
- **Unlock sectors as achievements:** add `unlocks_sector: str | None` to `ResearchRule`; engineering research **unlocks the `engineering` sector** (not just reveals the action). Research → unlock sector → high-tier action becomes usable.
- **Surface honestly:** `_render_action` reflects sector-lock in `available` + a `sector_locked`/`requires_sector` field, so `list_actions` doesn't show a gated action as freely available.
- **Why (Aetheria):** turns "click buttons until you win" into strategic expansion — it forces prioritization.

### 2. Risk tolerance → a living personality trait
Today `risk_tolerance` is tracked + clamped but nothing reads or moves it.
- **Perception:** add risk-tolerance perception notes to `_perception_notes` — low → a hesitant-about-experimental-actions note; high → a willing-to-gamble note. (Perception only — never changes physics.)
- **Dynamics (so it grows from her choices):** tag risky actions (`risk: int` or `experimental: bool` on `ActionRule`). A risky action that resolves without triggering a critical/crash nudges `risk_tolerance` up; an action that drives a critical resource to crash nudges it down. Clamped 0–10.
- **Why (Aetheria):** turns a dead number into a trait that shapes how she reads her own options — and one that *she* shifts by how she plays.

### 3. The reflection loop — the soul of the gym (PRIORITY)
Today `reason/regret/lesson` are written empty and nothing ever fills or reads them. This is the piece that makes it a gym.
- **Deterministic trigger (engine):** after an action, the engine sets a `pending_reflection` when a trigger fires — every `REFLECT_INTERVAL` cycles, OR on a major event (a sector unlock, a resource crash/critical, or run end). The trigger is engine-computed (a fact), not model-judged.
- **Forced, not optional:** while `pending_reflection` is set, further `execute_action` is **blocked** (`SandboxError: "reflection required"`) until she reflects. This structurally forces the post-game review Aetheria asked for.
- **Run-end is the most important reflection (ordering — Aetheria's catch):** if a critical resource crashes and the run ends, the engine sets `pending_reflection={"trigger": "run_end", …}` as part of the run-end transition — *after* `_check_run_end` flips `status="ended"`, in the same path, so the death trigger is never lost. Critically, `sandbox_reflect` is **exempt from the "run has ended" block**: it is the one and only action allowed on an ended run while a reflection is pending, so the death post-mortem (the most valuable lesson) is always captured. `execute_action` stays blocked on an ended run; only the final reflection gets through. After it's recorded, `pending_reflection` clears and the run remains ended.
- **The reflection itself (Aetheria, generative):** a new write tool `sandbox_reflect(reason, regret, lesson, run_id?)` records her reflection against the pending trigger — appended to a `reflections` record in run state AND back-filling the relevant `decision_log` entry's slots — then clears `pending_reflection`. She authors `reason/regret/lesson`; the engine never authors them (they stay "her meaning," per the boundary).
- **Read-back (optimize next run):** `sandbox_get_lessons(run_id?)` returns her prior reflections so she can carry pattern-knowledge forward — *within the gym's provenance only.*
- **Engine=facts, she=meaning:** the prompt that drives her reflection says "review the decision_log: what worked, what failed, what's the lesson?" — operating on the engine's recorded *deltas*. Facts deterministic; interpretation hers; both sandbox-local.
- **No real-cognition write:** `sandbox_reflect` writes only to sandbox run state. The bridge to the Lattice is `deliberate_share`, human-gated — out of scope for this code (it already exists).

### 4. Balance — real death-pressure (last, after wiring)
Once 1–3 are wired, tune the resource economy so the run is **not trivially survivable** — the risk of death must be real, or the lessons cost nothing. Playtest with scripted/long runs; adjust the constants in `rules.py` (starting resources, decay, effects, discovery thresholds). This is tuning + verification, done after the mechanics are correct.

## Architecture & components

- **`rules.py`:** add `unlocks_sector` to `ResearchRule` (engineering → "engineering"); add a risk tag to `ActionRule`; add `REFLECT_INTERVAL` + (post-playtest) tune constants.
- **`state.py`:** `initial_state` gains `pending_reflection: None` and `reflections: []`; `normalize_state` fills both (forward-compat for existing runs).
- **`engine.py`:** enforce `requires_sector` in `execute_action`; unlock sectors on research completion in `_advance_research`; risk-tolerance dynamics in the resource/crash path; `pending_reflection` trigger + the block-until-reflected gate; a `reflect(reason, regret, lesson, run_id?)` method; a `get_lessons(run_id?)` method; `_render_action` reflects sector-lock; `_perception_notes` reflects risk-tolerance.
- **`tools.py`:** two new Aetheria-only ToolSpecs — `sandbox_reflect` (write) and `sandbox_get_lessons` (read) — registered alongside the existing four via the same `build_*_tool`/`register_*_tools` pattern. (Aetheria-only ownership preserved; auto-audited via `ToolAuditEvent`.)
- **No change to the real cognition store, the Lattice, or `deliberate_share`.** The seam is that the sandbox simply never writes there.

## Error handling
- Reflecting with no `pending_reflection` → a clear `ToolArgError`, no-op (no fabricated reflection).
- Acting while reflection is pending → blocked with the "reflection required" message (the forcing mechanism, not an error to swallow).
- `sandbox_reflect` is allowed when a reflection is pending **regardless of run status** (active or ended) — it is exempt from the "run has ended" block so the death post-mortem is captured; every other action stays blocked on an ended run.
- A blocked `requires_sector` action returns the actionable message naming the sector to research (above).
- Empty/malformed reflection fields → validated at the tool boundary (non-empty `lesson` at minimum); the engine never auto-fills them.
- `normalize_state` keeps pre-existing runs (without the new fields) loadable.

## Testing
- **Sectors:** a `requires_sector` action is blocked before its sector is unlocked and usable after the unlocking research completes; `list_actions` shows it locked then available.
- **Risk tolerance:** a risky success raises it, a crash lowers it, clamped 0–10; perception notes change at the thresholds.
- **Reflection loop:** a trigger sets `pending_reflection`; `execute_action` is blocked until `sandbox_reflect` is called; `sandbox_reflect` records the reflection + clears the gate + back-fills the log slot; `sandbox_get_lessons` returns prior reflections.
- **Run-end reflection (the ordering test):** drive a critical resource to crash → assert `status=="ended"` AND `pending_reflection` is set with `trigger=="run_end"`; assert `execute_action` raises "run has ended" but `sandbox_reflect` **succeeds** on the ended run and records the final lesson; after it, `pending_reflection` is cleared and status stays ended.
- **Provenance seam (the critical test):** after a full play+reflect cycle, assert **nothing** was written to the cognition store / Lattice — reflections live only in sandbox run state. This test is the boundary's teeth.
- **Tools:** new tools registered for Aetheria only (not Vett/Scotty); engine-backed, no live model in tests.
- Determinism preserved (same seed + action+reflection sequence → identical state).

## Out of scope
- The Bridge into real cognition (it's `deliberate_share`, human-gated, already exists — the sandbox just never auto-writes).
- Any further persona/soul edits (explicitly — see the reverted Codex overreach; [[feedback_codex_less_guardrails]]).
- A web UI / visualization of runs.

## Two flags
1. **Prerequisite — commit the reviewed base first.** Codex's sandbox is currently uncommitted working-tree code (soul revert already applied). Commit the reviewed-sound base as a baseline *before* extending it, so this work builds on a committed foundation and the diff is clean. Attribution is Jon's call (Codex authored, Claude reviewed). The completion work is a separate commit series on top.
2. **Balance is playtest-gated.** Piece 4 needs real playthroughs; "correct mechanics" (1–3, unit-tested) is not the same as "good gym" (tuned for pressure). Don't declare it a gym until it's been played and death feels real.
