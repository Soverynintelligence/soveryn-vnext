"""Provenance-aware phrase rendering for Channel-A recall."""

from __future__ import annotations

from soveryn.platform.lattice.provenance import ProvenanceClass
from soveryn.platform.lattice.types import Entry, Region


class PhraseRenderError(ValueError):
    """Raised when an entry cannot be rendered as stateable recall."""


def render_phrase(entry: Entry) -> str:
    """Render a Channel-A entry using the locked provenance phrase map."""

    provenance = entry.provenance
    if provenance is None:
        raise PhraseRenderError("entry has no provenance")

    cls = provenance.cls
    if cls is ProvenanceClass.WITNESSED:
        return f"I remember {entry.content}"
    if cls is ProvenanceClass.TOLD:
        return _render_told(entry)
    if cls is ProvenanceClass.CONSOLIDATED:
        if provenance.source.startswith("legacy_"):
            return _render_legacy_promoted(entry)
        return f"I've come to understand {entry.content}"
    if cls is ProvenanceClass.INFERRED:
        basis = ", ".join(provenance.derived_from)
        return f"I infer {entry.content} because {basis}"
    raise PhraseRenderError(f"unsupported provenance class for Channel A: {cls}")


def _render_told(entry: Entry) -> str:
    source = entry.provenance.source if entry.provenance is not None else ""
    if source == "jon" or source == "user":
        return f"You told me {entry.content}"
    if source == "tool_output":
        return f"The tool output said {entry.content}"
    if source:
        return f"The notes from {source} say {entry.content}"
    return f"The notes say {entry.content}"


def _render_legacy_promoted(entry: Entry) -> str:
    if entry.region is Region.IDENTITY:
        return f"From older reviewed notes, I carry {entry.content}"
    return f"I found this in older reviewed notes: {entry.content}"
