"""Two-channel recall classification for Aetheria's speech boundary."""

from __future__ import annotations

from enum import StrEnum

from soveryn.platform.lattice.provenance import ProvenanceClass
from soveryn.platform.lattice.types import Entry


class Channel(StrEnum):
    """Speech-boundary channels."""

    A = "stateable_recall"
    B = "reason_only_context"


def classify_channel(entry: Entry) -> Channel:
    """Classify an entry into stateable recall or reason-only context."""

    if entry.metadata.get("canonical") is False:
        return Channel.B

    provenance = entry.provenance
    if provenance is None:
        return Channel.B

    cls = provenance.cls
    if cls is ProvenanceClass.LEGACY:
        return Channel.B
    if cls in {
        ProvenanceClass.WITNESSED,
        ProvenanceClass.TOLD,
        ProvenanceClass.CONSOLIDATED,
        ProvenanceClass.INFERRED,
    }:
        return Channel.A
    return Channel.B
