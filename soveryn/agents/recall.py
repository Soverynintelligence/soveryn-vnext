"""SOVERYN vNext — recall context formatter.

Pure function: rank-ordered Lattice nodes → deterministic multi-line
string suitable for a system-role ChatMessage. No I/O, no embedding
calls — formatting only. AgentLoop owns the query; this module owns
the layout.

Format example (one entry per recalled node):

    Recalled from memory (3 items, score >= 0.70):

    1. [0.87] Jon prefers Signal over Telegram for outbound notifications. — source: declared_fact
    2. [0.82] Aetheria's heartbeat runs as a thread inside app.py, not a separate process. — tags: architecture, runtime
    3. [0.74] Lattice schema mirrors production conversations.db verbatim.
"""

from __future__ import annotations

from soveryn.memory.lattice import Node


MAX_CONTENT_CHARS_PER_NODE = 200
MAX_TAGS_DISPLAYED = 3
ELLIPSIS = "..."


def _truncate(text: str, limit: int = MAX_CONTENT_CHARS_PER_NODE) -> str:
    """Deterministic single-line truncation."""
    flat = text.replace("\n", " ").replace("\r", " ").strip()
    if len(flat) <= limit:
        return flat
    return flat[: limit - len(ELLIPSIS)] + ELLIPSIS


def _suffix_for(node: Node) -> str:
    """`— source: X` or `— tags: a, b, c` or empty. Source wins if both."""
    if node.provenance and isinstance(node.provenance, dict):
        src = node.provenance.get("source_type")
        if isinstance(src, str) and src.strip():
            return f" — source: {src.strip()}"
    if node.tags:
        shown = list(node.tags)[:MAX_TAGS_DISPLAYED]
        return f" — tags: {', '.join(shown)}"
    return ""


def format_recall_context(
    ranked_nodes: tuple[tuple[Node, float], ...],
    *,
    threshold: float,
) -> str:
    """Render the recall preamble. Returns empty string when no nodes given —
    AgentLoop treats empty as 'omit the system message entirely'.

    Output is deterministic: same input → same string (sorted by score desc,
    which is also LatticeStore.find_nodes_by_embedding's output order).
    """
    if not ranked_nodes:
        return ""

    n = len(ranked_nodes)
    lines: list[str] = [
        f"Recalled from memory ({n} item{'s' if n != 1 else ''}, score >= {threshold:.2f}):",
        "",
    ]
    for idx, (node, score) in enumerate(ranked_nodes, start=1):
        body = _truncate(node.content)
        suffix = _suffix_for(node)
        lines.append(f"{idx}. [{score:.2f}] {body}{suffix}")
    return "\n".join(lines)
