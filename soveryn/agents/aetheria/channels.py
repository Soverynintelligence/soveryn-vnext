"""Two-channel recall classification for Aetheria's speech boundary."""

from __future__ import annotations

from enum import StrEnum

from soveryn.platform.lattice.provenance import ProvenanceClass
from soveryn.platform.lattice.types import Entry

# Pulse / dream essays are witnessed-shaped but not assertable spine facts.
_JOURNAL_REFLECTION_SOURCES = frozenset({
    "heartbeat",
    "dream_daemon",
    "dream",
})


class Channel(StrEnum):
    """Speech-boundary channels."""

    A = "stateable_recall"
    B = "reason_only_context"


def _is_journal_residue(entry: Entry) -> bool:
    """True for journal-grade pulse/dream residue — must not become \"I remember…\"."""

    meta = entry.metadata or {}
    if meta.get("grade") == "journal":
        return True
    tags = meta.get("tags") or ()
    for tag in tags:
        if str(tag) == "grade:journal":
            return True
    prov = meta.get("provenance")
    source = ""
    if isinstance(prov, dict):
        if prov.get("grade") == "journal":
            return True
        source = str(prov.get("source") or "")
    legacy_type = str(meta.get("legacy_type") or "")
    if legacy_type == "reflection" and source in _JOURNAL_REFLECTION_SOURCES:
        return True
    return False


def classify_channel(entry: Entry) -> Channel:
    """Classify an entry into stateable recall or reason-only context.

    Journal residue (heartbeat / dream essays) stays Channel B even when
    provenance.cls is WITNESSED — Memory Grades: Journal ≠ Spine/Atoms.
    """

    if entry.metadata.get("canonical") is False:
        return Channel.B
    if _is_journal_residue(entry):
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
