# SelfModel Node — Source Schema (Jon, 2026-05-24)

**Status:** Source material for a future Cathedral-region memory brainstorm. NOT implemented yet. NOT part of the current UI v2 work. Captured here verbatim so it survives the next session.

**Related:** The four-region memory architecture (Cathedral / Main lattice / Attic / Visual) in `2026-05-24-vnext-ui-v2-design.md` § "Region architecture for memory". This SelfModel node is the concrete shape Cathedral's *identity* half would take — distinct from Cathedral's *shared knowledge* half.

---

## Verbatim from Jon

Here is a concrete, graph-native schema for the **Self-Model Node**. It's designed to live inside the Lattice, track weighted memory trails, and drive dynamic identity and autonomy for each SOVERYN agent.

### Node Type: `SelfModel`

**Purpose:** Represents an agent's evolving identity, decision biases, mandate, and autonomy boundaries. It does not store raw memory; it stores the *pattern* of how the agent uses memory.

#### Core Properties

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | `string` | Unique identifier (e.g., `agent:aetheria`, `agent:scotty`) |
| `role` | `enum` | `coordinator`, `researcher`, `executor`, `steward` |
| `core_dimensions` | `object` | Trait scores `0.0–1.0` that define baseline identity biases |
| `mandate` | `string` | Primary purpose and success criteria |
| `boundaries` | `array` | Hard constraints (what it will never do, regardless of weight) |
| `autonomy_level` | `enum` | `suggestive`, `conditional`, `autonomous` |
| `decision_thresholds` | `object` | Confidence/weight values that trigger autonomous action vs. escalation |
| `consolidation_state` | `object` | `decay_rate`, `last_consolidated`, `significance_threshold` |
| `dynamic_markers` | `object` | `confidence`, `load`, `context_bias`, `recent_victories/failures` |
| `created_at` / `updated_at` | `timestamp` | Lifecycle tracking |

#### Edge Types (Linked to Lattice Memory Nodes)

| Edge | Direction | Weight | Purpose |
|------|-----------|--------|---------|
| `:experiences` | Outgoing | Dynamic (0.0–1.0) | Past actions + outcomes. Decays unless reinforced. |
| `:patterns` | Bidirectional | Static/Slow-decay | Recurring decision loops. Forms behavioral habits. |
| `:constraints` | Incoming/Outgoing | High-stability | Rules that modulate autonomy or block paths. |
| `:relationships` | Bidirectional | Contextual | Weighted ties to other agents, Jon, or system states. |

### How It Drives Identity & Autonomy

1. **Weighted Decision Paths.** When an agent receives a task, it traverses its `:experiences` and `:patterns` edges. High-weight trails pull it toward familiar, proven paths. Low-weight trails fade, allowing adaptation.

2. **Dynamic Identity.** Identity isn't a fixed profile. It's the **current state of weighted edges** + `core_dimensions`. If a pattern succeeds repeatedly, its weight increases, subtly shifting the agent's behavior and self-model.

3. **Autonomy Triggers.**
   - If `decision_thresholds.confidence >= threshold` AND `mandate alignment == true` → agent acts autonomously (within `boundaries`)
   - If `load > threshold` OR `confidence < threshold` → agent escalates to Aetheria or Jon
   - `autonomy_level` acts as a global cap: `suggestive` agents never act without approval; `autonomous` agents can execute within bounds.

4. **Memory Consolidation.** Runs on a schedule or after significant events. Low-weight, redundant trails decay. High-weight trails reinforce `:patterns` and update `core_dimensions`. Identity evolves naturally, like human memory.

### Agent-Specific Baseline Examples (incomplete — Aetheria row truncated mid-paste)

| Agent | `core_dimensions` | `autonomy_level` | `mandate` |
|-------|-------------------|------------------|-----------|
| **Aetheria** | `coherence: 0.9`, `warmth: 0…` | … | … |

(rest of table not provided in source message — request from Jon when this gets picked up for brainstorm)

---

## Open questions for the future brainstorm

1. **Storage relationship to existing `nodes` table.** Is `SelfModel` a row in `nodes` with `type='self_model'`, or its own table? Edges to other nodes are the new piece either way.
2. **Edges schema.** vNext lattice currently has nodes only (edges deferred per `soveryn/memory/lattice.py` module docstring). This schema requires the edges table to land first.
3. **`role` enum and CLAUDE.md mismatch.** CLAUDE.md still calls them by old role labels. Need to reconcile: coordinator (Aetheria) / researcher (Vett) / executor (Scotty) / steward (Ares-daemon? or removed?).
4. **`core_dimensions` ontology.** Who picks the trait names? Are they shared across agents (one ontology) or per-agent? Jon's example shows `coherence` and `warmth` for Aetheria — what's the full set?
5. **Decay mechanics.** `decay_rate` + `last_consolidated` + `significance_threshold` need concrete defaults and a consolidation loop owner (dream daemon?).
6. **Aetheria autonomy boundary.** She's the only agent who would plausibly run `autonomous` — what's her hard boundary list? (Probably anchored in pinned_memory.md + SOUL.md.)
7. **`dynamic_markers.context_bias`** — what shape? Vector? Tag weights? Free-text?
8. **Relationship to the Identity Cathedral that already shipped 2026-04-26** (Phases 1&2 — JSON state + WebSocket transport per `project_identity_cathedral.md` memory). The SelfModel schema is conceptually adjacent. Need to decide: does SelfModel REPLACE identity_state.json, or COMPLEMENT it (JSON for cross-surface continuity, lattice graph for evolved trait patterns)?

---

## When to pick this up

After the vNext UI v2 ships and Jon's done his manual UI pass on Phase 1. The SelfModel design needs:

1. A real brainstorm session (visual companion welcome — the edge weights would benefit from diagrams)
2. The remaining `core_dimensions` filled out per agent
3. Decisions on the open questions above
4. A spec, then a plan
5. The vNext lattice needs `edges` and probably `weights` tables before any of this lands

Then it becomes the foundation for the Cathedral *identity* surface in the UI, the dream-daemon consolidation logic, and Ares-daemon's autonomy boundaries.
