# Phase 2b-ii-b2 Baseline Audit

Phase 2b-ii-b2 is the live recall cutover. This audit records the pre-cutover state before implementation.

## Baseline

- HEAD before b2 implementation: `3e63ed1`
- Working tree before audit: clean
- Full test command: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q`
- Full test result: `798 passed in 5.46s`

## Current Live Recall Wiring

`soveryn/agents/loop.py` imports the old recall formatter:

```python
from soveryn.agents.aetheria.recall_policy import format_recall_context
```

There are two live recall call sites:

1. Sync path, `AgentLoop.process_message`, around lines 235-244:

```python
ranked = self.lattice_store.find_nodes_by_embedding(...)
recall_context = format_recall_context(ranked, threshold=self.recall_threshold)
```

2. Streaming path, `AgentLoop.process_message_stream`, around lines 324-331:

```python
ranked = self.lattice_store.find_nodes_by_embedding(...)
recall_context = format_recall_context(ranked, threshold=self.recall_threshold)
```

Both paths query `LatticeStore.find_nodes_by_embedding(...)` and then render raw legacy `Node` tuples through `format_recall_context(...)`.

## Target Wiring

Both live recall paths must render through the Phase 2b-ii-a two-channel assembler. The existing assembler accepts `Entry` objects, so the cutover needs a deterministic adapter from ranked legacy `Node` results to platform `Entry` evidence with parsed provenance.

Target behavior:

- Channel A canonical entries render under `Stateable recall:` with provenance phrases.
- Channel B raw/legacy/uncertain entries render only as uncertainty class/count under `Uncertain context:`.
- Channel B content must not appear in the recall system message.
- Empty/irrelevant recall still omits the recall system message.
- Recall remains read-only.

## Existing Data Preconditions

Phase 2b-ii-b1 is complete:

- `docs/PHASE2B_II_B1_VERIFY.md` exists.
- `docs/PHASE2B_II_B1_MIGRATION_REPORT.md` exists.
- vnext Attic contains the raw legacy corpus as low-confidence LEGACY material.
- vnext canonical lattice contains a 12-entry reviewed identity spine with `CONSOLIDATED` provenance and `source="legacy_identity_review"`.
- Runtime DBs are not committed.

## Do Not Touch

Out of scope for b2:

- No memory redesign.
- No persona edits.
- No recall threshold changes.
- No broad legacy promotion.
- No new migration pass.
- No Ares work.

## Rollback Requirement

The cutover must be revertible as one commit. Rollback should return live recall rendering to the pre-b2 path while leaving the b1 Attic migration and identity spine intact.
