"""Heartbeat salience digest renderer.

Plain-text block spliced into the heartbeat prompt. Visible scoring per
Aetheria's locked spec — she should be able to read off "C-Dist: 0.42 |
Marker: 'the realization is'" and tell us the engine is drifting if it is.
"""

from __future__ import annotations

from soveryn.platform.salience.store import SalienceCandidate


MAX_DIGEST_ITEMS = 5
RENDER_CONTENT_CHARS = 140


def build_salience_digest_section(
    candidates: list[SalienceCandidate],
) -> str:
    if not candidates:
        return ""
    items = candidates[:MAX_DIGEST_ITEMS]
    n = len(items)
    word = "moment" if n == 1 else "moments"
    lines: list[str] = [
        f"{n} {word} resonated since the last heartbeat. "
        "Do any feel like a permanent shift?",
        "",
    ]
    for c in items:
        head = (c.turn_content_head or "").strip()
        if len(head) > RENDER_CONTENT_CHARS:
            head = head[:RENDER_CONTENT_CHARS].rstrip() + "…"
        marker_label = (
            c.markers[0].marker if c.markers else "(novelty only)"
        )
        if c.novelty_score is not None:
            score_line = f'C-Dist: {c.novelty_score:.2f} | Marker: "{marker_label}"'
        else:
            score_line = f'Marker: "{marker_label}"'
        lines.append(f'- [{c.id}] {c.turn_role}: "{head}"')
        lines.append(f"  {score_line}")
    lines.append("")
    return "\n".join(lines)
