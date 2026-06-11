# Lattice + Embed Discovery — Vett Harness Phase 1

Date: 2026-06-11
Discoverer: vett-harness Task 5 (Opus 4.7 1M-context agent)
Branch: vett-harness-phase1
Source-of-truth commit at discovery time: 26042fdc62820c2f5d6810a4ac3b8f55053b3d46

## Lattice class

Single canonical class. Defined in `soveryn/platform/lattice/legacy.py` and re-exported by `soveryn/platform/lattice/__init__.py`. A compatibility shim at `soveryn/memory/lattice.py` re-exports the same names so existing call sites that import `soveryn.memory.lattice.LatticeStore` keep working. **Both paths reach the same `LatticeStore` class — there is no second implementation.** Use `soveryn.platform.lattice` for new code.

- **Import path (preferred)**: `soveryn.platform.lattice.LatticeStore`
  - Compat alias still live: `soveryn.memory.lattice.LatticeStore`
- **Constructor**:
  ```python
  LatticeStore(
      db_path: pathlib.Path,
      timeout_seconds: float = 30.0,
  )
  ```
  - Cheap. Opens SQLite connection per call inside a `_conn()` contextmanager (WAL mode). No background threads, no async, no warmup. Safe to instantiate per-process; not safe to share across threads without external locking (we won't need that in the harness CLI runner).
  - `_init_schema()` is idempotent — re-instantiating against an existing populated DB does nothing destructive.

- **Embedding retrieval**:
  ```python
  store.find_nodes_by_embedding(
      agent: str,                                # required positional — scoping agent
      embedding: tuple[float, ...],              # PRE-COMPUTED query vector — store does NOT embed for you
      *,
      limit: int = 10,
      threshold: float = 0.70,                   # cosine score floor
      layer_filter: str | None = None,           # None → agent's private+legacy+global (library excluded);
                                                 # "library" → library-only across all authors;
                                                 # other → that exact layer
  ) -> tuple[tuple[Node, float], ...]            # ordered score DESC, already truncated to `limit`
  ```
  - Linear cosine over up to 2000 candidate rows after a SQL pre-filter. No ANN index. Fine for 9k-node scale; would need work past ~100k.
  - Rows with NULL/malformed embeddings are silently skipped.

- **Keyword retrieval (also useful — likely Task 6 fan_out_search lever)**:
  ```python
  store.find_nodes_by_keywords(
      agent: str,
      query: str,
      *,
      limit: int = 20,
      include_global: bool = True,
  ) -> tuple[Node, ...]
  ```
  - Case-insensitive LIKE on `content` + `tags`. Excludes library. Ordered `salience DESC, updated_at DESC`.

- **Single-node lookup**:
  ```python
  store.get_node(node_id: str) -> Node | None
  ```
  - Bare PK lookup. Returns `None` (not raise) on miss.

- **Node type** (frozen dataclass, `soveryn.platform.lattice.legacy.Node`):
  ```python
  @dataclass(frozen=True)
  class Node:
      id: str
      type: str            # 'fact' | 'library' | 'direct_message' | legacy values…
      layer: str           # 'private' | 'global' | 'library' | legacy 'lattice'
      agent: str           # author
      content: str         # primary text payload
      intensity: float
      salience: float
      access_count: int
      tags: tuple[str, ...]
      created_at: str      # ISO datetime
      updated_at: str
      embedding: tuple[float, ...] | None
      intent: str | None
      provenance: dict | None
  ```
  - **There is no `.metadata` dict — relevant metadata is inlined as typed fields.** Provenance is the only dict-shaped field.

- **Multiple lattice classes?** No. The only other read-side class is `LegacyLatticeAdapter` (also in `legacy.py`), which is a thin platform-evidence wrapper returning `Entry` objects via `entry_from_node()`. It's used by the regions/attic memory layer, not by tools. Task 6 should call `LatticeStore` directly, not the adapter.

## Embedding entrypoint

- **Import path**: `soveryn.platform.lattice.embed_text` (preferred). Alias `soveryn.memory.lattice.embed_text` works via the shim. Aetheria's existing tool wiring uses `from soveryn.memory.lattice import embed_text as _default_embed` (`soveryn/agents/loop.py:49`).
- **Signature**:
  ```python
  def embed_text(text: str) -> tuple[float, ...]: ...
  ```
- **Sync/async**: sync. Blocking HTTP call.
- **Backend**: HTTP. Calls `soveryn.platform.inference.llama_server_client.embed(EmbeddingRequest(input=(text,)))`, which POSTs to `http://127.0.0.1:8090/v1/embeddings` with `model="embeddings"` (router preset alias from `MODEL_SERVERS` entry name=`"embeddings"` in `soveryn/config/runtime.py:101-107`). All four MODEL_SERVERS share port 8090 — the router (llama-server in router mode) dispatches by `model` field. The plan's earlier shorthand "`:8090 model=embeddings`" matches reality.
- **Vector dimension**: 768. Model is `nomic-embed-text-v1.5.Q8_0.gguf`. Vectors come back as `tuple[float, ...]`. The store does not enforce a dim — it just cosines pairwise — but mismatched dims silently degrade to score 0.0 (see `_cosine` early-out).

**Canonical call-site pattern (Aetheria's `search_lattice_by_embedding` tool)** at `soveryn/agents/aetheria/tools/search.py:25-37`:

```python
embedding = tuple(float(v) for v in embed_fn(query))
scored_nodes = store.find_nodes_by_embedding("aetheria", embedding, limit=k, threshold=threshold)
nodes = tuple(node for node, _score in scored_nodes)
```

Task 6 should mirror this pattern verbatim, just substituting `"vett"` for the agent arg and keeping the score if the harness wants to surface it.

## Lattice instantiation

- **Normal vnext path**: `soveryn/app/startup.py:101-104` — each app-startup invocation constructs its own `LatticeStore(env.recall_lattice_db)`. No process-wide singleton.
  ```python
  from soveryn.memory.lattice import LatticeStore
  recall_lattice = LatticeStore(env.recall_lattice_db)
  ```
  Aetheria's tools are then registered with `recall_lattice` injected as a kwarg, plus `embed_fn=_default_embed`.

- **Singleton available?**: No. There is no `from soveryn.memory.lattice import lattice as default_lattice` — every caller constructs its own. This is intentional (cheap; per-process; no shared-state hazard).

- **If no singleton, config source**: `soveryn.config.loader.load_env_config()` returns an `EnvConfig` dataclass. The relevant fields:
  - `recall_lattice_db: Path` — `$SOVERYN_RECALL_LATTICE_DB` env override, else `<data_root>/memory/lattice_vnext.db`
  - `lattice_db: Path` — `$SOVERYN_LATTICE_DB` env override, else `<data_root>/memory/lattice_vnext.db` (same file post-consolidation)
  - `data_root: Path` — `$SOVERYN_DATA_ROOT` env override, else `~/soveryn_vnext/data`

- **On-disk data path**: `/home/jon-deoliveira/soveryn_vnext/data/memory/lattice_vnext.db` (166 MB at discovery time, populated with ~9k+ nodes from the 2026-06-01 consolidation). WAL + shm sidecars present, indicating active app usage — Task 6 / 8 / 12 should NOT open this DB in destructive modes while the main app is running; read-only access via the standard `LatticeStore` API is safe (it opens WAL connections).

- **Phase-7 router note**: The embedding endpoint is dispatched through llama-server's router preset. The MODEL_SERVERS entry has `model_alias="embeddings"`, which `llama_server_client.embed()` uses as the `"model"` payload field. If router config drifts (alias renamed), `embed_text` raises `LookupError` immediately at the `_embeddings_server()` lookup or `LlamaServerError` at the HTTP layer — fail-fast, not silent.

## Implications for Task 6 (handlers)

The plan's example code in Task 6 assumed `find_nodes_by_embedding(query_embedding, top_k) -> Iterable[Node]` and `get_node(node_id) -> Optional[Node]` with `Node` exposing `.id` and `.content`. The actual API differs in these specific ways:

1. **Agent-scoped lookup, not global.** `find_nodes_by_embedding` requires an `agent: str` positional. The harness must pick a scoping agent — recommend `"vett"` (consistent with `AGENT_TO_SERVER` and so Vett's own private writes — if any — would surface). If Task 6's `search_corpus` is intended to search across the entire shared knowledge base, pass `layer_filter="library"` to get the cross-author library layer instead.
2. **Caller embeds first.** The store does not embed query strings — it takes a pre-computed `tuple[float, ...]`. Add an `embed_text(query)` call in the handler.
3. **Return is `(Node, score)` tuples, not bare Nodes.** Unpack: `for node, score in store.find_nodes_by_embedding(...)`.
4. **No `.metadata` attribute on Node.** Surface metadata via individual fields: `node.tags`, `node.agent`, `node.created_at`, `node.layer`. The closest thing to a generic metadata bag is `node.provenance` (a `dict | None`).
5. **Tool callable signature is `(params, overrides) -> Tuple[str, Optional[ToolCallMetadata]]`** (vendored `Tool.__call__` ABC at `soveryn/agents/vett/harness/vendor/tools.py:266-286`). Harness handlers return a `(text, metadata)` tuple, NOT a bare `str`. For initial port, `Optional[ToolCallMetadata]` can be `None` (or a stub `BaseModel` subclass — see `SearchCorpusToolCallMetadata` in vendor/tools.py for the pattern with `returned_chunk_ids`).
6. **`get_node` returns `None`, not raises**, when the id is missing. Handler must check.
7. **doc_id is the lattice node UUID** — flat, not chunked. The vendored ChromaDB read_document splits `<docid>_<chunkid>` and reassembles; **our lattice has flat nodes, not chunks**. The SOVERYN handler should NOT do the underscore split — just pass `doc_id` through to `get_node` and surface `node.content` as-is.

When Task 6 implements the harness `Tool` subclasses, the actual API to call is:

- `search_corpus(query: str) -> Tuple[str, Optional[ToolCallMetadata]]`:
  1. Embed: `embedding = embed_text(query)`  (or via injected `embed_fn` for testability)
  2. Search: `scored = store.find_nodes_by_embedding("vett", embedding, limit=k, threshold=t)`
  3. (Decide: include `layer_filter="library"` to draw from the shared library layer, or leave `None` to scope to Vett's private+global. For phase-1 cross-source eval Jon's likely target is library — confirm in Task 6.)
  4. Format: `"\n# DOCUMENT ID: {node.id}\n{node.content[:DOC_TRUNCATION]}"` per node (mirror the vendored format at `vendor/tools.py:469-480`)
  5. Metadata: optional Pydantic model carrying `returned_chunk_ids=[node.id for node, _ in scored]`

- `read_document(doc_id: str) -> Tuple[str, Optional[ToolCallMetadata]]`:
  1. Lookup: `node = store.get_node(doc_id)`
  2. Handle miss: return `("Document not found", None)` if `node is None`
  3. Format: `node.content` (full text — no chunk reassembly needed)
  4. Optionally truncate by token budget if Task 6 wires a token counter (the vendored read_document does this via reranker/truncate; the SOVERYN port can defer this to a follow-up since lattice nodes are typically short)

- `fan_out_search` (the third planned tool — also mentioned in the Task 6 brief): can build on `find_nodes_by_keywords` for the keyword leg + `find_nodes_by_embedding` for the embed leg. Task 6 should decide whether fan-out means parallel-tool-calls (the vendored `multi_tool_use` pattern at SCHEMA line 228) or multi-vector fan-out internally.

## Implications for Task 8 (`_build_agent`)

The plan's example `_build_agent` had placeholder imports:
```python
from soveryn.memory.lattice import lattice as default_lattice  # EXAMPLE
from soveryn.platform.inference.embed_client import embed_text  # EXAMPLE
```

Replace with the actual imports:
```python
from pathlib import Path
from soveryn.config.loader import load_env_config
from soveryn.memory.lattice import LatticeStore, embed_text
# (or use soveryn.platform.lattice for both — same symbols)

env = load_env_config()
lattice_store = LatticeStore(env.recall_lattice_db)
# embed_text is the function; wire it directly as embed_fn to the handlers.
```

Notes:
- There is no singleton to import. Build a fresh `LatticeStore` per CLI invocation. The cost is one SQLite open; safe.
- If the CLI runner needs to override the DB path (eval fixture, test data), expose a `--lattice-db PATH` flag and pass it to `LatticeStore(Path(arg))` directly, skipping `load_env_config()`.
- `embed_text` is the right callable to inject as `embed_fn`. For tests, inject a stub that returns a deterministic vector.

## Discovery verdict

**PASS — Task 6 and Task 8 can proceed with the actual API above.**

No blocker. Every harness need maps cleanly to a documented `LatticeStore` method, the embedding entrypoint is a single sync function call, the on-disk DB is at a predictable env-configurable path, and the canonical wiring pattern (constructor + inject `embed_fn`) is the same one Aetheria's tools have used in production since the 2026-06-01 consolidation.

Caveats Task 6 should keep in mind (none rise to blocker):

- **No ANN index** — at 9k nodes the linear cosine scan is fine; if eval workloads grow past ~100k nodes the lookup will start showing latency.
- **No test coverage at the lattice + harness boundary yet** — Aetheria's tools have unit tests (`soveryn/tests/agents/aetheria/tools/test_search.py` and adjacent); Task 6 should mirror that pattern with a small fixture DB to lock the contract in.
- **Agent-scoping decision is load-bearing.** `find_nodes_by_embedding("vett", …)` with `layer_filter=None` returns Vett's private rows + global rows, NOT the library. For phase-1 cross-source-link eval — where the corpus is conceptually shared reference material — Task 6 likely wants `layer_filter="library"`. Confirm this choice when wiring; it can be a tool kwarg / overrides field.
- **Live app uses the same DB.** `data/memory/lattice_vnext.db` has WAL/shm sidecars indicating the main app process is reading/writing it. Concurrent reads are safe; if Task 12's smoke test happens to write to the lattice it'll land in the same file the live app sees. Recommend Task 6/8 stay read-only against the production DB and that any harness-driven writes (if added later) go to a per-eval fixture path.
