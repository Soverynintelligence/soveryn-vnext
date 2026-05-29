# Phase 2b-ii-a Baseline + API Audit

Phase 2b-ii-a gate audit for the deterministic speech boundary. This commit records current live recall behavior and the locked speech-boundary design. No implementation happens in this task.

## Baseline

- HEAD at audit start: `f5b844e`
- `git status --short` at audit start: empty
- Full test command: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q`
- Full test result: `747 passed in 5.41s`

## Current Live Recall Formatter

File: `soveryn/agents/aetheria/recall_policy.py`

Live function signature:

```python
format_recall_context(
    ranked_nodes: tuple[tuple[Node, float], ...],
    *,
    threshold: float,
) -> str
```

Current behavior:

- Input is legacy `Node` objects from `soveryn.memory.lattice`, paired with scores.
- Empty input returns `""`; `AgentLoop` omits the recall system message.
- Header format: `Recalled from memory (N item(s), score >= THRESHOLD):`
- Each entry renders as `idx. [score] truncated_content + suffix`.
- Content is flattened and truncated to `MAX_CONTENT_CHARS_PER_NODE = 200` with `ELLIPSIS = "..."`.
- `_suffix_for(node)` reads `node.provenance["source_type"]` when present and renders ` — source: X`.
- If no usable source exists, `_suffix_for` renders up to `MAX_TAGS_DISPLAYED = 3` tags as ` — tags: a, b, c`.
- Source suffix wins over tags.

Live formatter tests:

- `tests/test_recall_formatter.py` covers empty output, header/count rendering, input order, singular/plural text, truncation, newline flattening, source suffix, tag suffix, source-over-tags precedence, tag cap, no suffix, malformed provenance fallback, determinism, and threshold formatting.
- `tests/test_aetheria_surfaces.py` confirms the compatibility shim re-exports the Aetheria recall policy.

**Phase 2b-ii-a rule:** this live formatter remains unchanged. New code is built alongside it and ships dark.

## Current AgentLoop Recall Path

File: `soveryn/agents/loop.py`

Current sync path:

1. Save the user turn.
2. Load history.
3. If `self.recall_k > 0`:
   - `query_vector = self.embed_fn(user_message)`
   - `ranked = self.lattice_store.find_nodes_by_embedding(self.agent_name, query_vector, limit=self.recall_k, threshold=self.recall_threshold)`
   - `recall_context = format_recall_context(ranked, threshold=self.recall_threshold)`
4. Build prelude system messages from persona/system prompt, pinned text, and soul text.
5. If `recall_context` is non-empty, append `ChatMessage(role="system", content=recall_context)` to the prelude.
6. Final messages are `prelude + history_messages`.

Current streaming path mirrors the same recall block and insertion rule:

- `find_nodes_by_embedding(...)`
- `format_recall_context(...)`
- append `ChatMessage(role="system", content=recall_context)` when non-empty

Current constructor defaults:

```python
recall_k: int = 0
recall_threshold: float = 0.70
```

Current recall tests:

- `tests/test_agent_loop.py` covers recall off by default, requiring a lattice store when recall is enabled, threshold validation, embedding + lattice query path, zero matches, empty lattice, embed failure, lattice failure, recall does not write to lattice, recall placement after persona, and empty persona behavior.
- `tests/test_agent_loop_stream.py` covers streaming recall inclusion.

**Prompt insertion point:** recall is inserted as a system message after persona/pinned/soul prelude and before conversation history. Phase 2b-ii-a must not change this live insertion point.

## Current Startup Recall Wiring

File: `soveryn/app/startup.py`

Current behavior:

- Startup checks `env.recall_lattice_db`.
- If present, it creates `LatticeStore(env.recall_lattice_db)` for read-only recall.
- Only Aetheria receives recall wiring.
- Vett and Scotty run with recall disabled.
- Aetheria receives:

```python
kwargs["lattice_store"] = recall_lattice
kwargs["recall_k"] = 5
kwargs["recall_threshold"] = 0.70
```

`tests/test_app_startup_recall.py` asserts:

- Aetheria gets recall when the recall DB exists.
- `recall_k == 5`.
- `recall_threshold == pytest.approx(0.70)`.
- Vett and Scotty do not get recall.
- Aetheria runs without recall when the recall DB is missing.
- Default recall path points at prod `soveryn_memory/lattice.db`, not `lattice_vnext.db`.

**Phase 2b-ii-a rule:** startup wiring and threshold `0.70` remain untouched. Live cutover is 2b-ii-b.

## 2b-i Modules Available To The New Assembler

### `platform/lattice/types.py`

`Region` members:

```text
episodic, semantic, procedural, identity, affective, unknown
```

`Entry` is frozen and has:

```python
id: str
content: str
region: Region = Region.UNKNOWN
source: str = "lattice"
metadata: dict[str, Any] = field(default_factory=dict)
private: bool = False
provenance: Provenance | None = None
```

### `platform/lattice/provenance.py`

`ProvenanceClass` currently has:

```text
WITNESSED = "witnessed"
TOLD = "told"
INFERRED = "inferred"
CONSOLIDATED = "consolidated"
LEGACY = "legacy"
```

`Provenance` is frozen and has:

```python
cls: ProvenanceClass | str
source: str
confidence: float
temporal_context: str
generator: str
chain: tuple[str, ...] = ()
derived_from: tuple[str, ...] = ()
```

Validation:

- `confidence` must be in `[0.0, 1.0]`.
- `chain` and `derived_from` normalize to tuples of non-empty strings.
- `INFERRED` requires non-empty `derived_from`.

Audit note: the locked speech design names `LEGACY_PROMOTED`, but the current 2b-i enum does not yet include it. 2b-ii-a classifier/renderer tasks must represent the locked legacy-promoted speech class explicitly while still leaving live recall dark.

### `platform/lattice/write_gate.py`

`WriteDecision`: `AUTO`, `CONFIRM`.

`classify_write(region, kind)`:

- `IDENTITY` and `AFFECTIVE` always `CONFIRM`.
- Interpretive kinds are `CONFIRM`.
- Structural/observational kinds are `AUTO`.
- Unknown kinds default to `CONFIRM`.

### `platform/lattice/attic.py`

Available structures:

- `AtticRecord(id, content, metadata, linked_lattice_ids, provenance, created_at)`.
- `AtticStore(db_path=...)` with SQLite-WAL storage.
- `append(...)` writes raw/non-canonical material.
- `fetch(...)` returns private, non-canonical `Entry` objects with `source="attic"`, `region=UNKNOWN`, `metadata["canonical"] = False`, and structured provenance.
- `get_record(attic_id)` retrieves raw Attic records.
- `promote(...)` creates a canonical Lattice node while leaving the raw Attic record unchanged.

### `platform/lattice/writer.py`

Available structures:

- `WriteResult(destination, lattice_id=None, attic_id=None)`.
- `LatticeWriter(lattice_store, attic_store, agent="aetheria")`.
- `LatticeWriter.write(content, region, kind, provenance, confirmed=False)`.
- Module helper `write(...)` with explicit store injection.

Behavior:

- AUTO writes land canonical via `LatticeStore.write_node(...)`.
- CONFIRM writes without `confirmed=True` route to Attic as pending/raw.
- CONFIRM writes with `confirmed=True` land canonical with confirmation metadata in provenance payload.

### `platform/lattice/facets.py`

Provisional metadata facets:

```text
working_context
pattern_reservoir
friction_log
salience_cache
```

Helpers:

- `get_facets(entry)`
- `add_facet(entry, facet)`
- `remove_facet(entry, facet)`
- `replace_facet(entry, old, new)`

Facets live in `Entry.metadata["facets"]`; they are not DB schema.

## Locked Channel Rules

From `2026-05-29-phase2b-ii-speech-boundary-design.md`:

- **Channel A: stateable recall.** Canonical, provenance-bearing entries. Aetheria may make memory claims from these using the locked provenance phrasing.
- **Channel B: reason-only context.** Attic, legacy-low-confidence, private, raw, uncertain, or unpromoted material. It may shape reasoning, caution, uncertainty, salience, and follow-up questions. It may not be quoted, cited, or asserted as remembered fact.
- **Core rule:** she may cite only Channel A. Channel B may only shape uncertainty. Legacy starts in B.
- **Channel B refinement:** Channel B is mentionable only as an uncertainty class, never as content. Allowed: “I have an uncertain older note related to this, but I can't treat it as memory yet.” Forbidden: “I have a note that says X.”

## Locked Phrase Map

- `WITNESSED` -> Channel A -> “I remember” / “I saw / read / called”.
- `TOLD` -> Channel A -> attribution mandatory: “You told me X” / “The tool output said X” / “The notes from Y say X”. It never collapses to bare “I remember”.
- `CONSOLIDATED` -> Channel A -> “I've come to understand…”.
- `INFERRED` with `derived_from` -> Channel A as inference, not recall -> “I infer X because Y” / “My read is X, based on Y” / “This looks like X from the pattern in Y”. Forbidden: “I remember X”, “I know X”, “X is true” unless separately supported by WITNESSED/TOLD/CONSOLIDATED.
- `LEGACY_PROMOTED` identity -> Channel A -> “From older reviewed notes, I carry X”.
- `LEGACY_PROMOTED` non-identity -> Channel A -> “I found this in older reviewed notes”.
- raw/unpromoted `LEGACY` -> Channel B -> uncertainty class only, no content.
- no backing entry -> no channel -> “I don't know”.

## No-Ghost Enforcement Shape

Locked approach: structural-primary plus behavioral floor.

Primary structural enforcement:

- A pure recall-context assembler receives supplied Channel A entries and supplied Channel B entries.
- The assembled context contains only supplied Channel A entries as quotable material.
- Channel B is rendered as uncertainty-class/no-content only.
- Tests assert Channel B content strings never appear in the quotable section.
- Tests assert unsupplied content cannot appear in the output.

Behavioral floor:

- Empty Channel A means no quotable recall section.
- All-Channel-B input means no quotable claims, only uncertainty signals.
- Fixture-level prompt shaping asserts there is no citable recall, establishing the deterministic precondition for “I don't know”.

No live model output parsing is part of 2b-ii-a.

## DO NOT TOUCH in Phase 2b-ii-a

These live surfaces are frozen until 2b-ii-b:

- `agents/aetheria/recall_policy.py`, especially `format_recall_context` and `_suffix_for`.
- `agents/loop.py` recall call to `format_recall_context`.
- `agents/loop.py` recall system-message insertion behavior.
- `app/startup.py` recall wiring.
- startup `recall_k=5`.
- startup `recall_threshold=0.70`.
- legacy migration / prod lattice copying.
- identity-review fast-track.
- persona text and souls files.
- live prompt integration / live cutover.

If any existing live recall test goes red, stop and classify. Do not patch formatter wording, threshold, AgentLoop prompt insertion, or persona text in 2b-ii-a.

## Ships-Dark Confirmation

The new two-channel assembler, channel classifier, phrase renderer, and uncertainty renderer will be built and fixture-tested in 2b-ii-a, but they are **not wired into AgentLoop** in this phase.

Live recall remains:

```text
AgentLoop -> LatticeStore.find_nodes_by_embedding(...) -> format_recall_context(...) -> ChatMessage(system, recall_context)
```

The live cutover is deferred to 2b-ii-b, after legacy migration and the bounded identity spine review. This avoids an “honest but hollow” window where all migrated prod memory is Channel B and nothing from her history is citable.

## Task 1 Gate

This audit is the gate for implementation. Phase 2b-ii-a Task 2 may start only after this document is committed alone with no source changes and the test suite remains green.
