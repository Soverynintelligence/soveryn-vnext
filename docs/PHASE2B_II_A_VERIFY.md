# Phase 2b-ii-a Verification

Phase 2b-ii-a built the deterministic speech boundary for Aetheria's future recall path. It is complete, tested, and intentionally dark: the new assembler is not wired into `AgentLoop`.

## Result

- Final HEAD before this docs commit: `c4c957a`
- Full test command: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q`
- Full test result: `775 passed in 5.45s`
- Live recall remains unchanged from the Phase 2b-ii-a baseline (`f5b844e`).

Live-recall unchanged check:

```bash
git diff f5b844e..HEAD -- \
  soveryn/agents/aetheria/recall_policy.py \
  soveryn/agents/loop.py \
  soveryn/app/startup.py
```

Result: empty diff.

Files changed during Phase 2b-ii-a:

- `docs/phase2b-ii-a-baseline-audit.md`
- `soveryn/agents/aetheria/channels.py`
- `soveryn/agents/aetheria/phrase_renderer.py`
- `soveryn/agents/aetheria/speech_assembler.py`
- `soveryn/agents/aetheria/uncertainty_renderer.py`
- `tests/test_aetheria_channels.py`
- `tests/test_phrase_renderer.py`
- `tests/test_speech_assembler.py`
- `tests/test_uncertainty_renderer.py`

No `format_recall_context`, `AgentLoop`, startup recall wiring, persona, threshold, or migration code changed.

## Built Components

- `classify_channel(entry)` splits entries into Channel A stateable recall vs Channel B reason-only context.
- `render_phrase(entry)` renders Channel A entries with the locked provenance phrase map.
- `render_uncertainty(entries)` renders Channel B as uncertainty class/count only, never content.
- `assemble_recall(entries)` composes deterministic two-section context:
  - `Stateable recall:` for quotable Channel A entries.
  - `Uncertain context:` for Channel B uncertainty signals.

Promoted legacy representation is dark and additive: reviewed legacy is represented as `ProvenanceClass.CONSOLIDATED` with `source` starting `legacy_`. Raw `LEGACY` remains Channel B.

## Proofs

Phrase renderer proof:

- `tests/test_phrase_renderer.py::test_told_by_user_requires_attribution_not_memory_language`
- `tests/test_phrase_renderer.py::test_told_by_tool_requires_tool_attribution`
- `tests/test_phrase_renderer.py::test_told_by_named_notes_requires_source_attribution`
- `tests/test_phrase_renderer.py::test_inferred_renders_as_inference_with_basis`
- `tests/test_phrase_renderer.py::test_legacy_reviewed_identity_renders_as_carried_identity`
- `tests/test_phrase_renderer.py::test_legacy_reviewed_nonidentity_renders_as_older_reviewed_notes`

No-ghost structural proof:

- `tests/test_speech_assembler.py::test_quotable_section_contains_only_supplied_channel_a_content`
- `tests/test_speech_assembler.py::test_channel_b_content_never_appears_in_quotable_section`
- `tests/test_speech_assembler.py::test_unsupplied_content_cannot_appear_in_assembled_context`

IDK floor proof:

- `tests/test_speech_assembler.py::test_empty_entries_produce_empty_recall_context`
- `tests/test_speech_assembler.py::test_all_channel_b_input_has_no_quotable_recall`
- `tests/test_speech_assembler.py::test_empty_quotable_context_shapes_i_do_not_know_floor`

Channel B content cannot leak through the uncertainty renderer because the renderer only counts entries and never reads `entry.content`.

## Dark-Ship Confirmation

The new speech boundary is built and fixture-tested, but not live. Current live recall is still:

```text
AgentLoop -> LatticeStore.find_nodes_by_embedding(...) -> format_recall_context(...) -> ChatMessage(system, recall_context)
```

The new assembler is not imported by `AgentLoop`, startup, or `format_recall_context`. Cutover is deferred to Phase 2b-ii-b after legacy migration and the bounded identity-review spine.

## Not Done Here

Phase 2b-ii-a does not do:

- Legacy migration or prod lattice copying.
- Identity-review fast-track.
- Live AgentLoop cutover.
- Persona changes.
- Recall threshold changes.
- Any prod-data tests.

## Sign-Off

Phase 2b-ii-a is complete. The deterministic speech boundary exists, the no-ghost boundary is proven structurally, the IDK floor is fixture-proven, and live recall remains unchanged.
