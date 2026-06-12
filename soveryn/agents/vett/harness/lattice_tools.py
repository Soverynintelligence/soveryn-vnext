"""Lattice-backed tool handlers for the vendored harness (read-through only).

The vendored harness dispatches tools like ``search_corpus`` and
``read_document`` to handler callables. This module provides those handlers
backed by SOVERYN's Synapse lattice. All handlers are pure read — no
writes to the lattice during phase 1.

Observation strings are formatted with the canonical
``# DOCUMENT ID: <id>\\n<text>`` marker so the vendored
``parse_doc_ids_from_observation`` (vendor/ultra_core.py) can recover IDs
downstream.

Vendor inspection notes (vendor/tools.py, captured during Task 6):

- ``Tool`` (vendor/tools.py:266) is an ABC + ``BaseModel``. Its
  ``__call__(params: Dict, overrides: Optional[Dict]) -> Tuple[str,
  Optional[ToolCallMetadata]]`` returns a (text, metadata) tuple, NOT a bare
  ``str``. ``ToolCallMetadata`` (line 260) is a ``BaseModel`` base; concrete
  subclasses (e.g. ``SearchCorpusToolCallMetadata`` line 324) carry
  ``returned_chunk_ids: List[str]``.
- Tools are registered via ``ToolSet`` (line 812), which wraps a list of
  ``Tool`` instances plus a name and exposes ``get_format(provider)`` per tool
  for schema attachment.
- Handlers in THIS module do NOT yet subclass ``Tool``. They are plain
  callables that Task 8's CLI runner / ``_build_agent`` will adapt into the
  ``Tool`` ABC (returning ``(text, None)`` or a minimal metadata stub).
  Keeping the contract simple here means tests don't need a Pydantic
  configuration / chromadb stub just to exercise lattice formatting.

Discovery context (see docs/notes/2026-06-11-lattice-discovery.md):
- ``LatticeStore.find_nodes_by_embedding(agent, embedding, *, limit,
  threshold, layer_filter)`` returns a tuple of ``(Node, score)`` tuples.
- ``LatticeStore.get_node(node_id)`` returns ``Node | None``.
- ``Node`` is a frozen dataclass with ``.id``, ``.content``, ``.agent``,
  ``.tags``, ``.layer``, ``.type``, ``.created_at``, ``.provenance``.
- ``embed_text(text) -> tuple[float, ...]``  (768-dim nomic-embed-text-v1.5).
"""
from __future__ import annotations

from typing import Callable, Iterable, List, Optional, Sequence, Tuple


DEFAULT_TOP_K = 5
DEFAULT_FAN_OUT_K = 3
_DEFAULT_AGENT = "vett"


def format_search_observation(items: Sequence[Tuple[str, str]]) -> str:
    """Render a list of ``(doc_id, text)`` as the harness-canonical marker format.

    The marker shape is exactly what ``vendor/ultra_core.py``
    ``parse_doc_ids_from_observation`` matches:
    ``re.findall(r'# DOCUMENT ID:\\s*(\\S+)', obs_text)``.
    """
    blocks = [f"# DOCUMENT ID: {doc_id}\n{text}".rstrip() for doc_id, text in items]
    return "\n\n".join(blocks)


class LatticeToolHandlers:
    """Tool handlers backed by SOVERYN's lattice (read-through only).

    Parameters
    ----------
    lattice
        A ``LatticeStore``-shaped object exposing:

        - ``find_nodes_by_embedding(agent: str, embedding, *, limit,
          threshold=0.0, layer_filter=None) ->
          Iterable[Tuple[Node, float]]``
        - ``get_node(node_id: str) -> Optional[Node]``

        Node-like objects must expose ``.id`` (str) and ``.content`` (str).
    embed_fn
        Callable returning a vector for a string query. Production wraps
        ``soveryn.memory.lattice.embed_text`` (sync HTTP to :8090).
    agent_name
        The agent identifier passed to
        ``LatticeStore.find_nodes_by_embedding``. Defaults to ``"vett"``.
    layer_filter
        Optional layer filter forwarded to
        ``LatticeStore.find_nodes_by_embedding``. ``None`` (the default)
        scopes searches to the agent's private + global layers and
        EXCLUDES the shared ``library`` layer. ``"library"`` searches the
        cross-author library layer only — recommended for phase-1
        cross-source eval where the corpus is shared reference material.
        Any other string is passed through verbatim (matches that exact
        layer name).
    """

    def __init__(
        self,
        *,
        lattice,
        embed_fn: Callable[[str], Sequence[float]],
        agent_name: str = _DEFAULT_AGENT,
        layer_filter: Optional[str] = None,
    ) -> None:
        self._lattice = lattice
        self._embed = embed_fn
        self._agent = agent_name
        self._layer_filter = layer_filter

    def search_corpus(self, *, query: str, top_k: int = DEFAULT_TOP_K) -> str:
        """Embed ``query``, vector-search lattice, format top-``k`` as observation."""
        embedding = self._embed(query)
        results = self._lattice.find_nodes_by_embedding(
            self._agent, embedding, limit=top_k,
            layer_filter=self._layer_filter,
        )
        # Real API returns iterable of (node, score); we only need (id, content).
        items = [(node.id, node.content) for node, _score in results]
        return format_search_observation(items)

    def fan_out_search(
        self,
        *,
        queries: Iterable[str],
        top_k_per_query: int = DEFAULT_FAN_OUT_K,
    ) -> str:
        """Run multiple queries (sync loop) and concatenate observations."""
        chunks: List[str] = []
        for q in queries:
            chunks.append(self.search_corpus(query=q, top_k=top_k_per_query))
        return "\n\n".join(chunks)

    def read_doc(self, *, doc_id: str) -> str:
        """Return the full content of a node by id, or a not-found observation.

        Lattice nodes are flat (no ``<docid>_<chunkid>`` chunk scheme like
        the vendored ChromaDB-backed ``ReadDocumentTool``). Pass ``doc_id``
        through to ``get_node`` and surface ``node.content`` verbatim.
        """
        node = self._lattice.get_node(doc_id)
        if node is None:
            return f"# DOCUMENT ID: {doc_id}\nDocument not found."
        return format_search_observation([(node.id, node.content)])
