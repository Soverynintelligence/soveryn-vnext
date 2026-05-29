"""Channel-B uncertainty rendering for Aetheria's speech boundary."""

from __future__ import annotations

from collections.abc import Iterable

from soveryn.platform.lattice.types import Entry


def render_uncertainty(entries: Iterable[Entry]) -> str:
    """Render Channel-B entries as uncertainty class only, never content."""

    count = sum(1 for _ in entries)
    if count == 0:
        return ""
    if count == 1:
        return "I have an uncertain older note related to this, but I can't treat it as memory yet."
    return f"I have {count} uncertain older notes related to this, but I can't treat them as memory yet."
