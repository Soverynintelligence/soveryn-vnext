"""Domain types for Coordination Boards."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


COORDINATION_NODE_TYPE = "coordination"
LESSON_LEARNED_NODE_TYPE = "lesson_learned"


class CoordBoard(str, Enum):
    """The three boards from Aetheria's locked spec."""
    SIGNAL = "Signal"
    BLUEPRINT = "Blueprint"
    FRICTION = "Friction"


class CoordStatus(str, Enum):
    """The four-state lifecycle: Open -> Refining -> Ready -> Archived."""
    OPEN = "Open"
    REFINING = "Refining"
    READY = "Ready"
    ARCHIVED = "Archived"


#: Valid one-step transitions. Anything not listed is rejected at the store.
#: Archive is terminal — nothing goes back from Archived.
VALID_TRANSITIONS: dict[CoordStatus, frozenset[CoordStatus]] = {
    CoordStatus.OPEN: frozenset({CoordStatus.REFINING, CoordStatus.ARCHIVED}),
    CoordStatus.REFINING: frozenset({CoordStatus.READY, CoordStatus.ARCHIVED}),
    CoordStatus.READY: frozenset({CoordStatus.ARCHIVED}),
    CoordStatus.ARCHIVED: frozenset(),
}


class CoordinationError(Exception):
    """Raised on validation / state errors in the coordination store."""


@dataclass(frozen=True)
class CoordinationNode:
    """A single Coordination Board entry.

    Storage shape: this lives in the lattice `nodes` table with
    type='coordination'. The board/status/lattice_ref carry in the provenance
    JSON column so we don't need a parallel table. owner is also kept in
    provenance for board-level filtering without joining back through agent.
    """
    id: str
    board: CoordBoard
    status: CoordStatus
    owner: str
    content: str
    lattice_ref: str | None
    archived_lesson_id: str | None
    created_at: str
    updated_at: str
