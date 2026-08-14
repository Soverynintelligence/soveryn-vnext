# Reasoned Representations — Design Spec (does it fit?)

**Date:** 2026-06-17
**Status:** design, grounded against current code. Not yet built.
**Decision:** Option A — steal the pattern from Honcho/Plastic Labs ("memory as reasoning"), build SOVERYN-native. No dependency, no repo. See memory `project_soveryn_reasoned_representations`.

**Goal:** systematize what the 12-node identity spine does by hand — maintain *evolving, reasoned representations* of Jon and each agent: atomic conclusions, each with its **premises + a natural-language confidence qualifier**, refined continually as new data confirms/contradicts them, queryable as context.

---

## Fit verdict: YES (every component already exists)

| Component | Honcho concept | SOVERYN substrate | Fit |
|---|---|---|---|
| Reasoning engine | "custom reasoning models" | **cognition surface** — Gemma 4 E4B Q8 on :8089 (CUDA2 Quadro) | ✅ already running; GPU has **~29 GB free**, no new slot |
| Store | "representations" | `nodes` table, `type='conclusion'`, structured fields in **`provenance` JSON** | ✅ **no schema migration** — provenance is already a JSON blob (coord + intent marks use it) |
| Premise/source links | conclusion ← premises | `edges` table (`relationship='concluded_from'`, strength) | ✅ exists |
| Background loop | "processed in the background" | **dream daemon** — tick loop + eligibility + 3-pass cognition + writeback | ✅ direct template; **contradiction pass already exists** |
| Reasoning modes | deductive/inductive/abductive | dream `prompt.py` render_* passes | ✅ same pattern |
| Surprisal / contradiction | refine on contradiction | dream's `render_contradiction_pass` | ✅ reusable |
| Query / injection | "scaffold reasoning at query time" | `_identity_spine_nodes` prelude injection + embedding recall (cross-agent visible per 2026-06-17 fix) | ✅ exists |

**Nothing requires new infrastructure, a schema migration, a new GPU slot, or an external dependency.** This is a new daemon + a node type + a prompt set, built from parts that already run.

---

## Data model (no migration)

A conclusion is a `nodes` row:
- `type = 'conclusion'`
- `layer = 'private'` (v1: each agent builds its own model; embedded on write so the owner recalls it)
- `content` = the conclusion in plain language ("Jon prefers the sharp honest read over the comforting one")
- `embedding` = set on write (recallable)
- `provenance` (JSON):
  ```json
  {
    "kind": "conclusion",
    "subject": "jon",                 // or an agent name
    "premises": ["<node:ID>", "..."], // what it was reasoned from
    "confidence": "fairly confident", // natural language, NOT numeric
    "mode": "abductive",              // deductive | inductive | abductive
    "run_id": "<uuid>",
    "supersedes": "<node:ID or null>" // set when revising a contradicted prior
  }
  ```
- `edges`: one `relationship='concluded_from'` edge from the conclusion to each premise node.

Reuses the dream daemon's `[node:ID]` citation convention so premises/edges extract the same way (`writeback.extract_node_pairs`).

---

## The representation daemon (mirror the dream daemon)

New `soveryn/agents/representation/` (sibling to `dream/`, same skeleton — do NOT overload dream; different concern):
- `trigger.py` — eligibility. Unlike dream (quiet-hours), this runs on **conversation activity**: tick every N min; eligible when `new_turn_count_since_last_run > 0`. Background/async — never blocks a chat turn.
- `cognition.py` — `run_representation_pass(briefing, cognition_url)`: feed recent turns + the subject's existing conclusions to the cognition surface; one reasoning call producing conclusions (mode + premises + NL-confidence, citing `[node:ID]`). Mirrors `dream.cognition.run_three_pass` / `chat_completion`.
- `prompt.py` — render the reasoning prompt: "given these premises and prior conclusions, what can you deductively/inductively/abductively conclude about <subject>? Cite premises by [node:ID]. Qualify confidence in plain words. Flag contradictions with prior conclusions."
- `writeback.py` — write conclusion nodes + `concluded_from` edges; on a flagged contradiction, **supersede** the prior (tag it `historical_snapshot`, set new node's `provenance.supersedes`) rather than duplicate. Mirrors `dream.writeback.write_dream_outputs`.
- `config.py` / `__main__.py` / systemd unit `soveryn-representation.service` — mirror dream's.

## Query / injection surface

- Extend `_identity_spine_nodes` (loop.py) to also surface `type='conclusion'` nodes for the agent, ranked by confidence×salience, capped (e.g. top-K) — injected as stable prelude alongside the curated spine.
- Plus normal embedding recall (already cross-agent visible).
- **Injection is bare data, never instruction** (`feedback_ambient_context_not_instruction`).

---

## Guardrails (load-bearing — bake in from v1)

- **Measurement ≠ Interpretation** (`project_soveryn_self_model_aggregation`): conclusions must be grounded in cited premises (source node IDs), not free interpretation. No mood-narration. A conclusion with no premises is invalid and dropped.
- **Confabulation risk** (abliteration/confab prior): the cognition model can fabricate. Mitigations: every conclusion cites auditable premises; low-confidence is surfaced as such, not hidden; dry-run mode first (like dream) to inspect output before it writes.
- **Not persona text** (`feedback_persona_text_substituting_for_memory_architecture`): this REPLACES hand-curated spine growth with reasoned memory — the right layer.

## Phasing

1. **P1 — skeleton + write path (dry-run).** Daemon mirrors dream; produces conclusions from recent turns; dry-run prints, doesn't write. Validate the reasoning output by eye.
2. **P2 — live writeback + edges.** Conclusion nodes + `concluded_from` edges; embedding on write.
3. **P3 — surprisal/refinement.** Contradiction detection → supersede prior conclusions.
4. **P4 — injection + recall tuning.** Surface conclusions in prelude; tune K/threshold.
5. **P5 (later) — fleet rollout + peer representations.** Run an instance per owner agent and let agents model Jon, the project, and each other (subject = entity name).

   **Owner-agent scope (LOCKED 2026-06-17):** reasoned representations are for **Aetheria + Vett only — NOT Scotty.** Scotty is a deliberately bounded instrument (no scope inference, stable behavior is his value); an evolving self-model would undermine that design. Aetheria + Vett both carry judgment/relationship and should develop a reasoned view of Jon and the work. Do not add Scotty as an owner "for completeness." (v1 still proves the loop on Aetheria→Jon first; Vett follows once validated.)

## What we are NOT doing
- Not adopting/self-hosting Honcho (avoids their v1.6→v2.0-style dependency churn).
- No `nodes` schema migration (provenance JSON carries the structure).
- No new GPU slot (cognition surface has headroom).
- Not overloading the dream daemon (separate concern → separate daemon).

## Open questions
- Trigger cadence + how many turns per briefing (token budget on the E4B's 16K ctx).
- Whether conclusions stay `private` or some graduate to `library`/`global` (shared model of Jon across agents). v1 = private.
- Interaction with the parked **self-model aggregation** engine (descriptive measurement) — conclusions could be an input to it. Keep them distinct: this REASONS, self-model MEASURES.
