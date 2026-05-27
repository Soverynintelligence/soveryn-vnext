"""Attic interface declarations.

The Attic is Aetheria's private memory overlay. Phase 1 declares the interface
without wiring storage or migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from soveryn.platform.lattice.types import Entry


@dataclass(frozen=True)
class AtticRecord:
    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    linked_lattice_ids: tuple[str, ...] = ()


class AtticStore:
    """Declared Attic storage boundary; implementation is deferred."""

    def append(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        *,
        linked_lattice_ids: tuple[str, ...] = (),
    ) -> AtticRecord:
        raise NotImplementedError("Attic storage is declared, not implemented in Phase 1")

    def fetch(self, query: str, *, include_links_to: str | None = None) -> tuple[Entry, ...]:
        raise NotImplementedError("Attic retrieval is declared, not implemented in Phase 1")
