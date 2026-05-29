# Phase 2b-i Baseline + API Audit

Phase 2b-i gate audit for provenance, write gate, and Attic storage. This commit records current behavior only. No implementation happens in this task.

## Baseline

- HEAD at audit start: `da29e4b`
- `git status --short` at audit start: empty
- Full test command: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q`
- Full test result: `701 passed in 4.90s`

## Current Platform Lattice Shapes

### `platform/lattice/types.py`

`Region(StrEnum)` members:

```text
EPISODIC = "episodic"
SEMANTIC = "semantic"
PROCEDURAL = "procedural"
IDENTITY = "identity"
AFFECTIVE = "affective"
UNKNOWN = "unknown"
```

`Entry` is a frozen dataclass with fields:

```python
id: str
content: str
region: Region = Region.UNKNOWN
source: str = "lattice"
metadata: dict[str, Any] = field(default_factory=dict)
private: bool = False
```

There is no first-class structured provenance field on `Entry`; current provenance, when present, is carried inside `metadata` or legacy `Node.provenance`.

### `platform/lattice/attic.py`

`AtticRecord` is a frozen dataclass with fields:

```python
id: str
content: str
metadata: dict[str, Any] = field(default_factory=dict)
linked_lattice_ids: tuple[str, ...] = ()
```

`AtticStore` is declared only. It has no constructor and both methods raise `NotImplementedError`:

```python
append(
    content: str,
    metadata: dict[str, Any] | None = None,
    *,
    linked_lattice_ids: tuple[str, ...] = (),
) -> AtticRecord

fetch(query: str, *, include_links_to: str | None = None) -> tuple[Entry, ...]
```

### `platform/lattice/legacy.py`

Layer constants:

```text
LAYER_PRIVATE = "private"
LAYER_GLOBAL = "global"
LAYER_LIBRARY = "library"
WRITE_LAYERS = {"private", "global", "library"}
```

Intensity/default constants:

```text
INTENSITY_DEFAULT = 0.3
INTENSITY_SIGNIFICANT = 0.7
INTENSITY_CORE = 1.0
DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0
DEFAULT_KEYWORD_LIMIT = 20
DEFAULT_EMBED_LIMIT = 10
DEFAULT_EMBED_THRESHOLD = 0.70
```

`Node` is a frozen dataclass with fields:

```python
id: str
type: str
layer: str
agent: str
content: str
intensity: float
salience: float
access_count: int
tags: tuple[str, ...]
created_at: str
updated_at: str
embedding: tuple[float, ...] | None
intent: str | None
provenance: dict | None
```

`region_for_node(node: Node) -> Region` is a conservative best-effort mapper:

- `identity`, `self`, `persona`, `soul` -> `Region.IDENTITY`
- `procedure`, `skill`, `howto`, `tool` -> `Region.PROCEDURAL`
- `event`, `conversation`, `journal`, `episode` -> `Region.EPISODIC`
- `mood`, `affect`, `salience` -> `Region.AFFECTIVE`
- `layer == LAYER_LIBRARY` or type `fact`, `concept`, `library` -> `Region.SEMANTIC`
- otherwise -> `Region.UNKNOWN`

`entry_from_node(node: Node) -> Entry` converts legacy nodes to `Entry` objects with:

- `source="legacy_lattice"`
- `region=region_for_node(node)`
- `private=node.layer == LAYER_PRIVATE`
- metadata containing legacy type, layer, agent, salience, intensity, access count, tags, timestamps, and optional legacy intent/provenance

`LatticeStore.__init__(db_path: Path, timeout_seconds: float = 30.0) -> None` opens/creates the SQLite store, enables foreign keys and WAL, and creates the legacy `nodes` table.

Current public methods relevant to Phase 2b-i:

```python
write_node(
    agent: str,
    content: str,
    *,
    node_type: str = "fact",
    layer: str = LAYER_PRIVATE,
    intensity: float = INTENSITY_DEFAULT,
    tags: tuple[str, ...] | None = None,
    embedding: tuple[float, ...] | None = None,
    intent: str | None = None,
    provenance: dict | None = None,
) -> str

get_node(node_id: str) -> Node | None

find_nodes_by_keywords(
    agent: str,
    query: str,
    *,
    limit: int = DEFAULT_KEYWORD_LIMIT,
    include_global: bool = True,
) -> tuple[Node, ...]

find_nodes_by_embedding(
    agent: str,
    embedding: tuple[float, ...],
    *,
    limit: int = DEFAULT_EMBED_LIMIT,
    threshold: float = DEFAULT_EMBED_THRESHOLD,
    layer_filter: str | None = None,
) -> tuple[tuple[Node, float], ...]
```

Read behavior to preserve in 2b-i:

- keyword search is case-insensitive over content/tags, ordered by `salience DESC, updated_at DESC`
- embedding search skips null/malformed embeddings, filters by cosine score, then sorts score descending
- default embedding threshold constant remains `0.70`
- reads tolerate legacy `layer='lattice'` rows even though writes reject that layer

`LegacyLatticeAdapter` is read-only by design:

```python
__init__(store: LatticeStore) -> None
fetch(
    query: str,
    *,
    agent: str,
    limit: int = DEFAULT_KEYWORD_LIMIT,
    include_global: bool = True,
) -> tuple[Entry, ...]
```

It exposes no `write_node`, `append`, or other write API.

### `agents/aetheria/recall_policy.py`

`format_recall_context` signature:

```python
format_recall_context(
    ranked_nodes: tuple[tuple[Node, float], ...],
    *,
    threshold: float,
) -> str
```

Current behavior:

- empty input returns `""`; `AgentLoop` omits the recall system message
- header is `Recalled from memory (N item(s), score >= THRESHOLD):`
- entries render as `idx. [score] content + suffix`
- content is flattened and truncated to 200 chars with `...`
- `_suffix_for(node)` checks `node.provenance["source_type"]` first and renders ` — source: X` if it is a non-empty string
- if no source suffix, it renders up to three tags as ` — tags: a, b, c`
- source wins over tags

This formatter is frozen in Phase 2b-i.

## Existing Lattice / Recall Test Files

Confirmed by `rg -l` under `tests/`:

- `tests/test_lattice.py` — legacy `LatticeStore` writes, layer validation, keyword search, embedding search, malformed embedding tolerance, cosine behavior.
- `tests/test_platform_lattice.py` — platform `Entry`, `Region`, read-only `LegacyLatticeAdapter`, private entry mapping, declared-not-implemented `AtticStore`, compatibility shim exports.
- `tests/test_recall_formatter.py` — exact recall formatter output, truncation, suffix/source/tag behavior, determinism, threshold display.
- `tests/test_agent_loop.py` — recall off by default, recall constructor validation, embedding query path, recall placement, failure propagation, and no write during recall.
- `tests/test_agent_loop_stream.py` — streaming path includes recall system message when enabled.
- `tests/test_app_startup_recall.py` — Aetheria-only recall startup wiring, `recall_k=5`, `recall_threshold=0.70`, graceful disable when recall DB missing, prod lattice default path.
- `tests/test_app_api_memory_routes.py` — `/api/memory/activity` route backed by `LatticeStore` read/count behavior.
- `tests/test_services_memory_activity.py` — direct SQLite read aggregation for daily memory write counts and total node count.
- `tests/test_aetheria_surfaces.py` — recall compatibility shim re-exports Aetheria recall policy.
- `tests/test_config_loader.py` — lattice and recall lattice path defaults/overrides.
- `tests/test_launcher.py` — launcher environment includes lattice and recall DB paths.
- `tests/test_platform_package.py` — `soveryn.platform.lattice` package import presence.

## Current Legacy Lattice Write Paths

`rg -n "write_node\("` found one production definition only:

- `soveryn/platform/lattice/legacy.py` defines `LatticeStore.write_node(...)`.

No live application code currently calls `write_node`. Current call sites are tests only:

- `tests/test_lattice.py`
- `tests/test_agent_loop.py`
- `tests/test_agent_loop_stream.py`
- `tests/test_platform_lattice.py`

Additional memory-related code reads the legacy SQLite table directly but does not write:

- `soveryn/app/services/memory_activity.py` uses `store._conn()` for `SELECT` aggregation.
- `soveryn/app/routes/api_memory.py` creates/caches `LatticeStore` and calls `daily_write_counts` / `total_node_count`.

`LegacyLatticeAdapter` exposes only `fetch(...)`; it has no write methods.

## Current Aetheria Read / Recall Paths

Current startup and loop chain:

1. `soveryn/app/startup.py` checks `env.recall_lattice_db`.
2. If the file exists, startup creates `LatticeStore(env.recall_lattice_db)` for Aetheria only.
3. Startup injects into Aetheria loop:
   - `lattice_store=recall_lattice`
   - `recall_k=5`
   - `recall_threshold=0.70`
4. Vett and Scotty receive `recall_k=0` and no lattice store.
5. `AgentLoop.process_message` and streaming path embed the user message, call `lattice_store.find_nodes_by_embedding(...)`, then pass results to `format_recall_context(...)`.
6. If the formatted recall context is non-empty, it is inserted as a system message after persona and before conversation/history/user content.

Current `AgentLoop.__init__` defaults:

```python
recall_k: int = 0
recall_threshold: float = 0.70
```

Current recall defaults from config:

- `DEFAULT_RECALL_LATTICE_DB = /home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice.db`
- `DEFAULT_LATTICE_DB = /home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db`

Current explicit safety comment in `config/loader.py`: `AgentLoop` only calls `find_nodes_by_*`, never `write_node`, against the recall DB.

`LegacyLatticeAdapter.fetch(...)` is tested and available, but Aetheria's current prompt recall path uses `LatticeStore.find_nodes_by_embedding(...)` directly, not the adapter.

## DO NOT TOUCH in Phase 2b-i

These surfaces are frozen until Phase 2b-ii:

- `agents/aetheria/recall_policy.py`, especially `format_recall_context` and `_suffix_for`
- recall prompt wording, including the `Recalled from memory...` header
- recall placement in `AgentLoop`
- recall threshold tuning; leave startup threshold `0.70` unchanged
- persona text and souls files
- legacy migration behavior
- `LatticeStore.find_nodes_by_keywords` semantics
- `LatticeStore.find_nodes_by_embedding` semantics
- current Aetheria startup recall wiring
- current compatibility shims (`soveryn.memory.lattice`, `soveryn.agents.recall`)

If any recall/lattice behavior test goes red during Phase 2b-i, stop and classify before patching. Do not compensate with persona text, thresholds, prompt wording, or recall formatter changes.

## Gaps Phase 2b-i Closes

- `Entry` has no first-class structured provenance field.
- There is no provenance model with source class, confidence validation, generator, temporal context, or derivation chain.
- `AtticStore` is declared but unimplemented.
- There is no provenance-aware canonical write path alongside legacy `write_node`.
- There is no tiered write gate enforcing structural auto-write vs interpretive/identity/affective review.
- There is no additive promotion path proving raw Attic material remains intact.
- Aetheria-local facets (`working_context`, `pattern_reservoir`, `friction_log`, `salience_cache`) are not represented yet as provisional metadata labels.

## Task 1 Gate

This audit is the gate for implementation. Phase 2b-i Task 2 may start only after this document is committed alone with no source changes and the test suite remains green.
