"""Shared content budgets for lattice write/read paths.

Canonical location for Memory Grades caps (design 2026-08-11). Lives under
``platform/lattice`` so write_node, dream writeback, and tool render can share
one source of truth without platform importing agents.

See: docs/superpowers/specs/2026-08-11-memory-grades-self-through-memory-design.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal


# ── Write / storage caps (chars) ─────────────────────────────────────────────

CONTENT_CAPS: dict[str, int] = {
    "fact": 400,
    "lesson_learned": 400,
    "decision": 400,
    "conclusion": 400,
    "trigger_anchor": 200,
    "insight": 600,
    "reflection": 500,
    "identity": 600,
    "library": 800,
    "event": 800,
    "coordination": 1200,
    "x_post": 400,
    "deliberate_share": 800,
    "direct_message": 400,
    "_default": 800,
}

WRITE_HARD_CEILING = 12_000
JOURNAL_MAX_CHARS = 8_000
DREAM_SYNTHESIS_LATTICE_MAX = 600
LIBRARY_PROMOTE_MAX_CHARS = 800

# ── Tool render caps (list mode) ─────────────────────────────────────────────

CHANNEL_B_TOOL_TOP_N = 5
CHANNEL_B_BODY_MAX_CHARS = 400
CHANNEL_A_BODY_MAX_CHARS = 400
DETAIL_MODE_MAX_CHARS = 12_000

OverflowPolicy = Literal["clamp", "raise"]


class ContentOverflowError(ValueError):
    """Raised when content exceeds the type cap and on_overflow='raise'."""

    def __init__(self, node_type: str, length: int, limit: int) -> None:
        self.node_type = node_type
        self.length = length
        self.limit = limit
        super().__init__(
            f"content for type={node_type!r} is {length} chars; "
            f"limit is {limit} (set on_overflow='clamp' to truncate)"
        )


def cap_for_type(node_type: str) -> int:
    """Return the per-type content cap (chars)."""
    key = (node_type or "").strip() or "_default"
    return CONTENT_CAPS.get(key, CONTENT_CAPS["_default"])


def clamp_content(
    node_type: str,
    content: str,
    *,
    on_overflow: OverflowPolicy = "clamp",
    max_chars: int | None = None,
) -> str:
    """Clamp or reject content against the type budget.

    Shared by write_node (PR2) and bypass writers (dream raw INSERT).
    Always enforces WRITE_HARD_CEILING as a backstop after the type cap.
    """
    text = content if content is not None else ""
    limit = max_chars if max_chars is not None else cap_for_type(node_type)
    limit = min(limit, WRITE_HARD_CEILING)

    if len(text) <= limit:
        return text

    if on_overflow == "raise":
        raise ContentOverflowError(node_type or "_default", len(text), limit)

    if limit <= 1:
        return "…" if text else ""
    # Prefer a clean cut; ellipsis marks truncation for readers.
    return text[: limit - 1].rstrip() + "…"


def truncate_body(text: str, max_chars: int) -> tuple[str, bool, int]:
    """Truncate for tool list mode. Returns (body, truncated, original_chars)."""
    original = text if text is not None else ""
    n = len(original)
    if n <= max_chars:
        return original, False, n
    if max_chars <= 1:
        return "…", True, n
    return original[: max_chars - 1].rstrip() + "…", True, n


def resolve_full_text_ref(
    ref: str,
    *,
    data_root: Path | None = None,
) -> str | None:
    """Load archived full text for a provenance full_text_ref.

    Supported schemes (implemented incrementally as writers land):
      - thoughts_log:pulse_id=<uuid>
      - dream_archive:<run_id>
      - journal_archive:<id>

    Returns None if the ref is empty, unknown, or the archive is missing.
    Callers must treat None as honest miss (detail mode sets full_text_missing).
    """
    if not ref or not str(ref).strip():
        return None

    # Archives land with PR3/PR4/PR8. Resolver is wired now so detail mode can
    # call it without ImportError; returns None until those files exist.
    _ = data_root  # reserved for path resolution
    return None
