"""Self-initiated recall tool — agents query their own lattice mid-work.

Layer-4 groundwork (self-model roadmap 2026-10-02/03): recall in loop.py fires
on the user message only (reactive). This tool lets a seat notice "wait, I've
seen this before" and consult its own memory because IT decided to — the
difference between a database and a mind.

Mirrors build_remember_fact_tool's shape (see lattice/teach.py). Reuses the
same embed + cosine path as AgentLoop._build_recall_context, so results match
what the prelude recall would have surfaced — the seat just gets to ask.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from soveryn.platform.tools.registry import ToolSpec

DEFAULT_K = 6
DEFAULT_THRESHOLD = 0.30


def build_memory_recall_tool(
    lattice_store: Any,
    owner_agent: str,
    *,
    embed_fn: Callable[..., tuple[float, ...]],
    default_k: int = DEFAULT_K,
    threshold: float = DEFAULT_THRESHOLD,
    description: str = (
        "Search your own memory (lattice) on demand. Use when YOU notice a "
        "connection mid-work — not only when the user's message already "
        "triggered recall. Query embeddings rank against stored nodes the "
        "same way turn-start recall does; this is you asking, not the "
        "system injecting."
    ),
) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        query = str(args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "query is required"}
        k_raw = args.get("k")
        try:
            k = int(k_raw) if k_raw is not None else default_k
        except (TypeError, ValueError):
            k = default_k
        k = max(1, min(k, 20))
        include_historical = bool(args.get("include_historical", False))

        # Librarian asymmetric prefix: queries embed as "query" (matches
        # loop.py recall). Fall back for test fakes without the kwarg.
        try:
            query_vector = embed_fn(query, prompt="query")
        except TypeError:
            query_vector = embed_fn(query)

        try:
            ranked = lattice_store.find_nodes_by_embedding(
                owner_agent,
                query_vector,
                limit=k,
                threshold=threshold,
                include_historical=include_historical,
            )
        except Exception as exc:  # noqa: BLE001 — tool surface returns error dict
            return {"ok": False, "error": str(exc)}

        from soveryn.agents.aetheria.speech_assembler import assemble_ranked_recall

        text = assemble_ranked_recall(ranked)
        return {
            "ok": True,
            "query": query,
            "n_hits": len(ranked),
            "recall": text,
        }

    return ToolSpec(
        name="memory_recall",
        owner=owner_agent,
        description=description,
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search your memory for. Natural language.",
                },
                "k": {
                    "type": "integer",
                    "description": f"Max hits (1-20, default {default_k}).",
                },
                "include_historical": {
                    "type": "boolean",
                    "description": (
                        "Set true to include historical_snapshot nodes "
                        "(archival). Default false: current-state only."
                    ),
                },
            },
            "required": ["query"],
        },
        handler=handler,
    )
