"""Two-channel recall context assembly for Aetheria."""

from __future__ import annotations

from collections.abc import Iterable

from soveryn.agents.aetheria.channels import Channel, classify_channel
from soveryn.agents.aetheria.phrase_renderer import render_phrase
from soveryn.agents.aetheria.uncertainty_renderer import render_uncertainty
from soveryn.platform.lattice.types import Entry

QUOTABLE_RECALL_HEADING = "Stateable recall:"
UNCERTAINTY_HEADING = "Uncertain context:"


def assemble_recall(entries: Iterable[Entry]) -> str:
    """Assemble a deterministic two-channel recall context from supplied entries."""

    channel_a: list[Entry] = []
    channel_b: list[Entry] = []
    for entry in entries:
        if classify_channel(entry) is Channel.A:
            channel_a.append(entry)
        else:
            channel_b.append(entry)

    sections: list[str] = []
    if channel_a:
        sections.append(_render_quotable_section(channel_a))

    uncertainty = render_uncertainty(channel_b)
    if uncertainty:
        sections.append(f"{UNCERTAINTY_HEADING}\n- {uncertainty}")

    return "\n\n".join(sections)


def _render_quotable_section(entries: list[Entry]) -> str:
    lines = [QUOTABLE_RECALL_HEADING]
    lines.extend(f"- {render_phrase(entry)}" for entry in entries)
    return "\n".join(lines)
