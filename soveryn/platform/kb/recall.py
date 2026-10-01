"""One recall door, two stores. Lattice = memory. KB = reference."""
from __future__ import annotations

from typing import Sequence

from soveryn.platform.kb.store import KBHit, KBStore
from soveryn.platform.lattice.legacy import (
    DEFAULT_EMBED_LIMIT,
    DEFAULT_EMBED_THRESHOLD,
    LatticeStore,
    embed_text,
    entry_from_node,
)
from soveryn.platform.lattice.types import Entry


def recall(
    query: str,
    *,
    agent: str,
    lattice: LatticeStore | None = None,
    kb: KBStore | None = None,
    sources: Sequence[str] = ("lattice", "kb"),
    limit: int = DEFAULT_EMBED_LIMIT,
    threshold: float = DEFAULT_EMBED_THRESHOLD,
    embed_fn=None,
) -> tuple[Entry, ...]:
    """Embed once, query the requested stores, merge by score descending.

    ``embed_fn`` is for tests. Production uses the same ``embed_text`` path
    as the lattice (query prompt).
    """
    wanted = {s.strip().lower() for s in sources}
    encode = embed_fn or (lambda text: embed_text(text, prompt="query"))
    vec = encode(query)

    scored: list[tuple[float, Entry]] = []
    if "lattice" in wanted and lattice is not None:
        for node, score in lattice.find_nodes_by_embedding(
            agent, vec, limit=limit, threshold=threshold
        ):
            entry = entry_from_node(node)
            scored.append((float(score), entry))
    if "kb" in wanted and kb is not None:
        hits = kb.search(vec, k=limit)
        for hit, entry in zip(hits, kb.as_entries(hits)):
            if hit.score < threshold:
                continue
            scored.append((hit.score, entry))

    scored.sort(key=lambda item: item[0], reverse=True)
    return tuple(entry for _, entry in scored[:limit])


def format_kb_hits(
    hits: Sequence[KBHit],
    *,
    threshold: float,
    limit: int,
    max_chars: int = 400,
) -> str:
    """Render reference hits as a prelude block. Empty if nothing clears the bar."""
    lines: list[str] = []
    for hit in hits:
        if hit.score < threshold:
            continue
        body = " ".join((hit.content or "").split())
        if not body:
            continue
        if len(body) > max_chars:
            body = body[: max_chars - 3] + "..."
        src = hit.source_path or hit.chunk_id
        lines.append(f"- ({src}) {body}")
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    return "Reference:\n" + "\n".join(lines)
