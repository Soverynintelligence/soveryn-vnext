"""Shared platform memory interface types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Region(StrEnum):
    """Declared memory regions. Taxonomy remains revisable before Aetheria cutover."""

    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    IDENTITY = "identity"
    AFFECTIVE = "affective"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Entry:
    """Platform evidence object returned by memory mechanisms.

    `content` is evidence text, not an instruction to claim ability, tool access,
    or write authority. Agent packages decide how, or whether, to voice it.
    """

    id: str
    content: str
    region: Region = Region.UNKNOWN
    source: str = "lattice"
    metadata: dict[str, Any] = field(default_factory=dict)
    private: bool = False
