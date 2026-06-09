"""Cross-Surface Continuity — brief renderer (pure function).

Turns SessionTail tuples into the `[CROSS-SURFACE RECENT ACTIVITY]` block
Aetheria sees above pinned memory. Empty input returns "" — the common
case where nothing has happened on other rails costs zero context.

Per-session token cap drops oldest paired turns; total budget drops
oldest sessions. Head content trimmed to CONTENT_HEAD_CHARS with an
ellipsis. Relative time in m/h.
"""

from __future__ import annotations

from datetime import datetime

from soveryn.platform.continuity.config import ContinuityConfig
from soveryn.platform.continuity.store import PairedTurn, SessionTail


BLOCK_HEADER = "[CROSS-SURFACE RECENT ACTIVITY]"
BLOCK_FOOTER = "[/CROSS-SURFACE RECENT ACTIVITY]"
CONTENT_HEAD_CHARS = 140


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def _truncate_head(content: str) -> str:
    collapsed = " ".join(content.split())
    if len(collapsed) <= CONTENT_HEAD_CHARS:
        return collapsed
    return collapsed[:CONTENT_HEAD_CHARS] + "…"


def _format_relative_time(updated_at: str, now: datetime) -> str:
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return updated_at
    delta = now - updated
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return "just now"
    total_minutes = total_seconds // 60
    if total_minutes < 60:
        return f"{total_minutes}m ago"
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if minutes == 0:
        return f"{hours}h ago"
    return f"{hours}h{minutes}m ago"


def _render_session_block(
    tail: SessionTail, pairs: tuple[PairedTurn, ...], now: datetime
) -> str:
    title = tail.title or "(untitled session)"
    rel = _format_relative_time(tail.updated_at, now)
    lines: list[str] = [f'— from "{title}" ({rel}):']
    for pair in pairs:
        user_head = _truncate_head(pair.user)
        lines.append(f'   jon: "{user_head}"')
        if pair.assistant is None:
            lines.append("   aetheria: (in flight)")
        else:
            asst_head = _truncate_head(pair.assistant)
            lines.append(f'   aetheria: "{asst_head}"')
    return "\n".join(lines)


def _fit_session_to_cap(
    tail: SessionTail, cap: int, now: datetime
) -> tuple[str, int]:
    """Trim oldest pairs until the rendered block fits the per-session cap.

    Keeps at least one pair even if oversized — head truncation does the
    final mile.
    """
    pairs = tail.paired_turns
    while True:
        block = _render_session_block(tail, pairs, now)
        tokens = estimate_tokens(block)
        if tokens <= cap or len(pairs) <= 1:
            return block, tokens
        pairs = pairs[1:]


def build_recent_activity_brief(
    tails: tuple[SessionTail, ...],
    *,
    config: ContinuityConfig,
    now: datetime | None = None,
) -> str:
    if not tails:
        return ""
    if now is None:
        now = datetime.now()
    preamble = (
        f"In the last {config.window_hours} hours you also exchanged "
        "turns with Jon on other rails:"
    )
    # Overhead: header + preamble + blank line + footer, joined by newlines.
    skeleton = "\n".join([BLOCK_HEADER, preamble, "", BLOCK_FOOTER])
    running = estimate_tokens(skeleton)
    rendered: list[str] = []
    for tail in tails:
        block, block_tokens = _fit_session_to_cap(
            tail, config.per_session_cap, now
        )
        # Each additional block adds a blank-line separator beyond the first.
        added = block_tokens + (estimate_tokens("\n\n") if rendered else 0)
        if running + added > config.token_budget:
            break
        rendered.append(block)
        running += added
    if not rendered:
        return ""
    body = "\n\n".join(rendered)
    return "\n".join([BLOCK_HEADER, preamble, "", body, BLOCK_FOOTER])
