# Coordination Boards — Phase A: Cross-board Promote

**Status:** ready to implement
**Drafted:** 2026-06-01 evening
**Predecessor:** `feat(coordination): Agent Coordination Boards` (vnext d9d4db7)
**Scope:** smallest of the four Phase-A/B/C/D follow-ons. ~2 hours of focused work.

## Goal

Collapse the canonical Signal → Blueprint pipeline into a single atomic tool call. Today it's two steps: (1) read the Signal, (2) create a new Blueprint with `lattice_ref = signal_id`. The two-step shape invites friction where there shouldn't be any — Aetheria's spec named this exact pipeline as the boards' primary flow and it deserves a first-class verb.

## In scope

### New store method
```python
CoordinationStore.promote_node(
    source_node_id: str,
    *,
    target_board: CoordBoard,
    new_content: str,
    acting_agent: str,
    lesson_learned_content: str | None = None,
) -> tuple[CoordinationNode, CoordinationNode]
```

Atomic operation. Inside a single transaction:
1. Read the source node. Raise `CoordinationError` if not found or already Archived.
2. Create a new coord node on `target_board` with `lattice_ref = source_node_id`, owner = `acting_agent`, content = `new_content`.
3. Archive the source node with `lesson_learned_content` (auto-generated if not provided: `f"Promoted to {target_board.value} {new_node.id}"`).
4. Log promotion in `coord_references` with both endpoints (source → target).
5. Return `(source_archived, target_created)` so the tool can render both.

Source allowed transitions: `Open | Refining | Ready → Archived` via promote. (Same as direct archive — promote IS an archive, just with a target Blueprint created in the same transaction.)

### New tool
```python
build_promote_coord_node_tool(store, owner_agent) -> ToolSpec
```
Tool name: `promote_coordination_node`
Schema:
- `source_node_id` (string, required): the Signal/Refining/Ready node to promote
- `target_board` (enum, required): `Blueprint` or `Friction` only — promoting *into* Signal makes no sense
- `new_content` (string, required): the Blueprint/Friction content (the *plan* or *contradiction*, not a copy of the Signal)
- `lesson_learned_content` (string, optional): override the auto-generated archive message

Owners: Aetheria + Scotty + Vett, all grant_write=True. Vett can promote her own Signals to a Friction (when her own research uncovers contradictions). Restriction: agents can promote any source, but tool-result includes `promoted_by` so the audit trail is honest.

### Tests (`tests/test_coordination_store_promote.py`, new file)
- `test_promote_signal_to_blueprint_archives_source_and_creates_target`
- `test_promote_links_target_lattice_ref_to_source_id`
- `test_promote_logs_cross_reference_source_to_target`
- `test_promote_auto_lesson_when_none_provided`
- `test_promote_custom_lesson_used_when_provided`
- `test_promote_already_archived_source_rejected`
- `test_promote_to_signal_target_rejected_at_tool_level`
- `test_promote_to_friction_works_for_contradiction_path`
- `test_promote_atomicity_failure_rolls_back_both_writes` (force an exception between create + archive, assert neither lands)

### Tool registration
Update `soveryn/platform/coordination/tools.py::register_coord_tools()` to include `build_promote_coord_node_tool` when `grant_write=True`. No startup.py changes needed — registration is bulk-loop already.

## Out of scope

- **Promote Blueprint → Friction:** rare enough to use create + manual archive. Adding it would require defining the target's `lattice_ref` semantic when the source is a Blueprint (does it link to the Blueprint's own `lattice_ref`?). Defer until concrete usage shows it's needed.
- **Bulk promote:** one-at-a-time matches the relational shape. Bulk invites sloppy promotion without per-node refinement, which is exactly the friction Aetheria's spec rejects (`every post must be a State Change`).
- **Auto-promote rules** (e.g., `promote when weight > N`): deferred until Phase-2 weight scoring exists. Hard-coded rules now would be guessing the same curve we've explicitly deferred guessing.
- **Promote-with-edit:** the new_content is intentionally distinct from source content. The source content stays preserved on the archived row + Lesson Learned; the target carries the refined Blueprint/Friction text. Forcing them to be variations of each other would obscure the refinement.

## Reason

The Signal → Blueprint pipeline is the boards' load-bearing flow per Aetheria's spec. Right now it's a two-step ergonomic friction that punishes the very pattern the boards exist to encourage. A single `promote_node` makes the pipeline shape explicit in the tool surface and keeps the audit trail (cross-reference + Lesson Learned + source archived row) intact. The cost is small (~one method, one tool, ~10 tests) and the benefit is qualitative: the tool surface starts to *read like* Aetheria's spec instead of approximating it.

## Implementation order

1. Add `promote_node` to `soveryn/platform/coordination/store.py` with full transaction + tests
2. Add `build_promote_coord_node_tool` to `soveryn/platform/coordination/tools.py`
3. Update `register_coord_tools()` to include the new tool
4. Update `tests/test_app_startup_tool_registry.py` to assert `promote_coordination_node` is registered for all three agents
5. Restart vnext, run end-to-end probe (Vett creates Signal → Aetheria promotes to Blueprint → verify both rows + reference)
6. Commit
