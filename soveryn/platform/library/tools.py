"""Library layer tool factories.

Two tools per agent: write_library_node (creates a layer='library'
lattice node) and search_library (embedding-based lookup restricted to
the library layer). No new tables — the substrate is the existing
`nodes` table with the layer column.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from soveryn.platform.lattice.legacy import LAYER_LIBRARY, LatticeError, LatticeStore
from soveryn.platform.lattice.miss_hint import build_miss_hint
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


WRITE_LIBRARY_TYPE = "library"        # nodes.type for library-written facts
WRITE_LIBRARY_INTENSITY = 0.6         # higher than default 'fact' — verified, reference-quality
SEARCH_LIBRARY_DEFAULT_K = 5
SEARCH_LIBRARY_MAX_K = 25


def build_write_library_node_tool(
    *,
    lattice_store: LatticeStore,
    owner_agent: str,
    embed_fn=None,
) -> ToolSpec:
    """Tool for writing a node to the library layer. Available to all three
    agents — the library is shared reference material; attribution survives
    via the agent column.

    embed_fn (optional): when provided (prod wires nomic-embed), the node is
    embedded on write so it's recallable by every agent's semantic recall.
    None in tests → unembedded (no HTTP). Best-effort: embed failure never
    blocks the write."""

    def _maybe_embed(text):
        if embed_fn is None or not text:
            return None
        try:
            return tuple(embed_fn(text[:8000]))
        except Exception:
            return None

    def handler(args: Mapping[str, Any]) -> Any:
        content = args.get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise ToolArgError("content must be a non-empty string")
        tags_arg = args.get("tags") or []
        if not isinstance(tags_arg, list) or not all(isinstance(t, str) for t in tags_arg):
            raise ToolArgError("tags must be a list of strings (omit if none)")
        try:
            node_id = lattice_store.write_node(
                agent=owner_agent,
                content=content.strip(),
                node_type=WRITE_LIBRARY_TYPE,
                layer=LAYER_LIBRARY,
                intensity=WRITE_LIBRARY_INTENSITY,
                tags=tuple(tags_arg) if tags_arg else None,
                embedding=_maybe_embed(content.strip()),
                provenance={
                    # cls + source are BOTH required by
                    # _provenance_from_payload; without cls the entry parses to
                    # None and falls to Channel B, unassertable. 1,045 nodes were
                    # in that state until 2026-08-03 — real provenance the reader
                    # could not read.
                    "cls": "witnessed",
                    "source": "library_write",
                    "written_by": owner_agent,
                },
            )
        except LatticeError as e:
            raise ToolArgError(str(e))
        return {
            "id": node_id,
            "layer": LAYER_LIBRARY,
            "written_by": owner_agent,
            "content_head": content.strip()[:200],
        }

    return ToolSpec(
        name="write_library_node",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": (
                        "The verified fact / reference material to persist. Library "
                        "entries are permanent reference material visible to every "
                        "agent — use this for things you've verified and would want "
                        "your future self (and the rest of the fleet) to be able to "
                        "look up. NOT for unverified leads (those go to Signal board)."
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of short string tags for grouping (e.g. "
                        "['funding', 'eu', 'horizon-europe']). Helps later "
                        "discovery; not required."
                    ),
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Persist a verified fact or piece of reference material to the shared "
            "library layer in the lattice. Library entries are permanent, "
            "cross-agent visible, and stable (no lifecycle states). Use for things "
            "you've actually verified — for unverified leads, post a Signal to the "
            "coordination boards instead. Library writes do NOT trigger webhook "
            "events; other agents see them when they next search the library or "
            "via their heartbeat's lattice-activity summary."
        ),
    )


def build_search_library_tool(
    *,
    lattice_store: LatticeStore,
    embed_fn: Callable[[str], tuple[float, ...]],
    owner_agent: str,
) -> ToolSpec:
    """Embedding-similarity search restricted to the library layer.

    Default per-agent lattice search (search_lattice_by_embedding) excludes
    library rows when no layer_filter is set. This tool is the opposite —
    library-only, regardless of caller agent."""

    def handler(args: Mapping[str, Any]) -> Any:
        query = args.get("query", "")
        if not isinstance(query, str) or not query.strip():
            raise ToolArgError("query must be a non-empty string")
        k = args.get("k", SEARCH_LIBRARY_DEFAULT_K)
        if not isinstance(k, int) or k <= 0:
            raise ToolArgError("k must be a positive integer")
        if k > SEARCH_LIBRARY_MAX_K:
            raise ToolArgError(f"k must be <= {SEARCH_LIBRARY_MAX_K}")
        threshold = args.get("threshold", 0.5)
        if not isinstance(threshold, (int, float)):
            raise ToolArgError("threshold must be a number")
        threshold = float(threshold)

        embedding = embed_fn(query.strip())
        # Library search: pass layer_filter='library' so we get library rows
        # specifically. The lattice's find_nodes_by_embedding signature treats
        # the calling agent as the scoping agent for non-library searches; for
        # layer_filter='library' it returns library-typed rows across all
        # authors (which is the point — shared reference).
        results = lattice_store.find_nodes_by_embedding(
            owner_agent,
            embedding,
            limit=k,
            threshold=threshold,
            layer_filter="library",
        )
        rendered = []
        for r in results:
            # find_nodes_by_embedding yields tuples in different shapes across
            # call sites; be defensive about the structure.
            node = r[0] if isinstance(r, tuple) else r
            score = r[1] if isinstance(r, tuple) and len(r) > 1 else None
            rendered.append({
                "id": node.id,
                "content": node.content,
                "written_by": node.agent,
                "tags": list(node.tags) if node.tags else [],
                "created_at": node.created_at,
                "similarity": score,
            })
        payload: dict[str, Any] = {"results": rendered, "count": len(rendered)}
        # Miss Hint — when the library search came up empty, probe the other
        # layers with a coarse keyword scan so the caller sees where similar
        # content lives. Mirrors the Aetheria search-tool hook (see
        # soveryn/agents/aetheria/tools/search.py); same per-layer count
        # payload shape so consumers can treat both uniformly.
        if not rendered:
            payload["miss_hint"] = build_miss_hint(lattice_store, owner_agent, query)
        return payload

    return ToolSpec(
        name="search_library",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural-language search query. Embedding similarity is "
                        "computed against library entries; the closest matches "
                        "above the threshold are returned."
                    ),
                },
                "k": {
                    "type": "integer",
                    "description": (
                        f"How many results to return at most. Default "
                        f"{SEARCH_LIBRARY_DEFAULT_K}, cap {SEARCH_LIBRARY_MAX_K}."
                    ),
                },
                "threshold": {
                    "type": "number",
                    "description": (
                        "Minimum cosine similarity (0.0-1.0) to include a result. "
                        "Default 0.5. Lower = more recall, higher = more precision."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Search the shared library layer for verified reference material. "
            "Library entries are written by any agent and visible to all. "
            "Returns matches with content, the agent who wrote it, tags, "
            "timestamp, and similarity score."
        ),
    )


def register_library_tools(
    registry: ToolRegistry,
    *,
    lattice_store: LatticeStore,
    embed_fn: Callable[[str], tuple[float, ...]],
    owner_agent: str,
) -> None:
    """Register both library tools for one agent. Same tools, owner-keyed."""
    registry.register(build_write_library_node_tool(
        lattice_store=lattice_store, owner_agent=owner_agent, embed_fn=embed_fn,
    ))
    registry.register(build_search_library_tool(
        lattice_store=lattice_store, embed_fn=embed_fn, owner_agent=owner_agent,
    ))
