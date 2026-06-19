"""Active Focus — the work currently in flight, derived on-read from the
non-archived coordination boards and folded into Aetheria's cross-surface
context. The active-state half of the continuity work (2026-06-19): she carries
awareness of what's actively being worked on across every rail, not just the
recent conversation tail.

Source is the coordination boards (Signal/Blueprint/Friction), NOT intent-marks
— deliberate_share/mark_share are empty in practice; the boards are where the
live work actually lives (verified 2026-06-19). Bare data, never instruction
(feedback_ambient_context_not_instruction). No LLM — pure render over nodes,
derive-on-read at brief assembly (as fresh as a cache, no cache to invalidate).
"""
from __future__ import annotations

from collections.abc import Iterable

BLOCK_HEADER = "[ACTIVE FOCUS]"
BLOCK_FOOTER = "[/ACTIVE FOCUS]"
_HEAD_CHARS = 110
DEFAULT_CAP = 5


def _head(content: str) -> str:
    collapsed = " ".join((content or "").split())
    if len(collapsed) <= _HEAD_CHARS:
        return collapsed
    return collapsed[:_HEAD_CHARS] + "…"


def _value(x) -> str:
    return x.value if hasattr(x, "value") else str(x)


def render_active_focus(nodes: Iterable, *, cap: int = DEFAULT_CAP) -> str:
    """Render non-archived coordination nodes as the ACTIVE FOCUS block.

    `nodes` are CoordinationNodes from `CoordinationStore.list_nodes()` (already
    archive-excluded, ordered created_at ASC). We show the most-recent `cap`,
    newest first. Empty input → "" (the block simply doesn't appear).
    """
    active = list(nodes)[::-1][:cap]
    if not active:
        return ""
    lines = [BLOCK_HEADER, "Work currently in flight across the boards:"]
    for n in active:
        lines.append(f"— [{_value(n.board)} · {_value(n.status)}] {_head(n.content)}")
    lines.append(BLOCK_FOOTER)
    return "\n".join(lines)
