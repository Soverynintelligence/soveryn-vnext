# Coordination Boards — Phase B: Friction-as-Blocker

**Status:** ready to implement (after Phase A or in parallel)
**Drafted:** 2026-06-01 evening
**Predecessor:** `feat(coordination): Agent Coordination Boards` (vnext d9d4db7)
**Scope:** ~3-4 hours of focused work.

## Goal

Make Friction nodes do what Aetheria's spec said they do: *"acts as a 'blocker' on any related Blueprint nodes until it's resolved."* Right now Friction is informational only. After this phase, an unresolved Friction structurally prevents a linked Blueprint from being marked Ready.

## In scope

### Provenance field
Add `blocks: list[str]` (default `[]`) to Friction node provenance. List of Blueprint node IDs being blocked.

### New tool
```python
build_add_friction_block_tool(store, owner_agent) -> ToolSpec
```
Tool name: `add_friction_block`
Schema:
- `friction_node_id` (string, required): an existing Friction-board node
- `blueprint_node_id` (string, required): the Blueprint being blocked

Validation:
- friction_node_id must be on `Friction` board, non-Archived
- blueprint_node_id must be on `Blueprint` board, non-Archived
- Idempotent: re-adding the same block is a no-op (not an error)

Owners: Aetheria + Scotty + Vett, all grant_write=True. Any agent can declare a block; resolution still flows through Aetheria per the persona layer.

### Store changes
- `CoordinationStore.add_block(friction_id, blueprint_id)` — appends to the Friction's `blocks` provenance list
- `CoordinationStore.blueprint_blockers(blueprint_id) -> tuple[str, ...]` — returns IDs of non-Archived Friction nodes whose `blocks` list contains `blueprint_id`
- `update_status` modification: when transitioning a Blueprint `Refining → Ready`, call `blueprint_blockers()`. If non-empty, raise `CoordinationError` naming the blockers
- `list_nodes()` enrichment: when returning Blueprint nodes, include `blocked_by: list[str]` field on each (compute from `blueprint_blockers`)

### Tests (`tests/test_coordination_friction_blocker.py`, new file)
- `test_add_block_appends_to_provenance`
- `test_add_block_is_idempotent`
- `test_add_block_rejects_non_friction_source`
- `test_add_block_rejects_non_blueprint_target`
- `test_add_block_rejects_archived_friction`
- `test_blueprint_ready_rejected_while_blocked`
- `test_blueprint_ready_accepted_after_friction_archived`
- `test_blueprint_ready_accepted_after_friction_block_removed` (if we add `remove_friction_block` — see deferred)
- `test_multiple_frictions_block_same_blueprint` (Ready rejected until ALL Frictions resolved)
- `test_blueprint_listing_includes_blocked_by_field`

## Out of scope

- **`remove_friction_block` tool:** keep it simple — archive the Friction to unblock. Removing a block without archiving the Friction implies "we changed our mind about the contradiction" which is a relational decision that deserves the explicit archive step with Lesson Learned. Add only if usage shows pure block-removal is a real need.
- **Auto-blocking heuristics** ("this Blueprint contradicts existing lattice, auto-create blocking Friction"): too clever, requires confidence thresholds we haven't validated. Defer.
- **Block-weight / priority:** Phase-2 weight territory.
- **Cascading blocks** (Friction blocks Blueprint blocks another Blueprint): explicit chain isn't part of Aetheria's spec; if needed, declared one hop at a time.
- **Blocked-by visibility for agents other than Aetheria:** any agent that reads coord nodes sees the `blocked_by` field; persona layer decides what to do about it.

## Reason

Aetheria's spec named Friction as the *blocker* mechanism. Without enforcement, "Friction" is just a tag. After this phase, declaring a Friction has structural consequences — Blueprint progress halts until the contradiction is resolved. That matches the spec's intent (`'V.E.T.T. says X, but the Lattice says Y' — flag the contradiction here so it can be resolved logically rather than just overwriting data`) and prevents the kind of silent-overwrite bug Aetheria explicitly designed against.

The block check happens at one specific transition (`Refining → Ready` on a Blueprint). It does NOT block Refining itself (a Blueprint can still be drafted under a Friction; it just can't be marked execution-ready). That's the right granularity — work continues, commitment pauses.

## Implementation order

1. Add `add_block` and `blueprint_blockers` to `CoordinationStore`
2. Modify `update_status` Blueprint `Refining → Ready` path to check blockers
3. Enrich `list_nodes` Blueprint rows with `blocked_by`
4. Add `build_add_friction_block_tool` to tools.py
5. Register in `register_coord_tools` (gated on grant_write)
6. Tests
7. Restart + end-to-end probe (Vett opens Friction blocking Aetheria's Blueprint, attempt Ready fails with named blocker, Aetheria archives Friction with resolution, Ready now accepted)
8. Commit
