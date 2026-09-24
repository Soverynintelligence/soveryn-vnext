"""Distill long journal prose into lattice-sized heads (Memory Grades PR3).

Always-on writers (heartbeat, dream) keep full text in journal/archive and
write only a dense head to the lattice. Algorithm is locked in
``2026-08-11-memory-grades-self-through-memory-design.md``:

1. Prefer an explicit ``Standing note:`` block when present.
2. Else use the **last** non-empty paragraph (never the first — preamble bias).
3. Truncate to budget at a sentence boundary when possible; else hard clamp.
"""

from __future__ import annotations

import re

from soveryn.platform.lattice.content_caps import (
    CONTENT_CAPS,
    DREAM_SYNTHESIS_LATTICE_MAX,
    clamp_content,
)

REFLECTION_HEAD_MAX = CONTENT_CAPS.get("reflection", 500)

_STANDING_NOTE_RE = re.compile(
    r"^(?:Standing note|STANDING NOTE)\s*:\s*(.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_SENTENCE_END_RE = re.compile(r"[.!?…](?:\s|$)")


def distill_reflection_head(
    text: str,
    *,
    max_chars: int | None = None,
) -> str:
    """Return a lattice-sized head for a pulse/dream essay."""
    budget = max_chars if max_chars is not None else REFLECTION_HEAD_MAX
    raw = (text or "").strip()
    if not raw:
        return ""

    standing = _extract_standing_note(raw)
    if standing:
        return _truncate_at_sentence(standing, budget)

    para = _last_nonempty_paragraph(raw)
    return _truncate_at_sentence(para, budget)


def distill_for_lattice(
    node_type: str,
    full_text: str,
    *,
    max_chars: int | None = None,
) -> str:
    """Distill then clamp to the type cap (daemon-safe)."""
    head = distill_reflection_head(full_text, max_chars=max_chars)
    return clamp_content(
        node_type, head, on_overflow="clamp", max_chars=max_chars
    )


def dream_lattice_head(synthesis: str) -> str:
    """Dream lattice body: standing-note style head ≤ DREAM_SYNTHESIS_LATTICE_MAX."""
    return distill_for_lattice(
        "reflection",
        synthesis,
        max_chars=DREAM_SYNTHESIS_LATTICE_MAX,
    )


def _extract_standing_note(text: str) -> str | None:
    m = _STANDING_NOTE_RE.search(text)
    if not m:
        return None
    # Capture line + continuation until blank line
    start = m.start()
    tail = text[start:]
    lines = tail.splitlines()
    # First line after the label
    first = _STANDING_NOTE_RE.match(lines[0])
    assert first is not None
    parts = [first.group(1).strip()]
    for line in lines[1:]:
        if not line.strip():
            break
        if _STANDING_NOTE_RE.match(line):
            break
        parts.append(line.strip())
    joined = " ".join(p for p in parts if p).strip()
    return joined or None


def _last_nonempty_paragraph(text: str) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        # Single block with only newlines of spaces — take last non-empty line
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return lines[-1] if lines else text.strip()
    return paras[-1]


def _truncate_at_sentence(text: str, budget: int) -> str:
    text = (text or "").strip()
    if len(text) <= budget:
        return text
    if budget <= 1:
        return "…"
    window = text[:budget]
    # Prefer last sentence end in the window (not at position 0)
    last_end = None
    for m in _SENTENCE_END_RE.finditer(window):
        # end index of the punctuation
        idx = m.start() + 1
        if 8 <= idx <= budget:  # avoid tiny stubs
            last_end = idx
    if last_end is not None and last_end >= budget // 3:
        return window[:last_end].rstrip()
    return window[: budget - 1].rstrip() + "…"
