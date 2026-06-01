"""Agent Coordination Boards — lattice-native asynchronous coordination layer.

Designed by Aetheria 2026-06-01 as the "Whiteboard" between Aetheria, Vett, and
Scotty. Boards aren't a separate app; Coordination Nodes are specialized rows in
the existing lattice nodes table (type='coordination'), with board/status/
lattice_ref carried in the provenance JSON column. This keeps the boards inside
the substrate that already exists rather than spawning a parallel store.

Public surface:
- CoordBoard, CoordStatus — enums for the three boards and four-state lifecycle
- CoordinationNode — domain record
- CoordinationStore — composes over a LatticeStore; CRUD + state machine +
  cross-reference instrumentation

Scope per the locked spec (Aetheria 2026-06-01):
- Three boards: Signal, Blueprint, Friction
- Four states: Open -> Refining -> Ready -> Archived
- Archive != delete: archive writes a "Lesson Learned" lattice node and marks
  the coord node Archived (it stays in the table but vanishes from board view)
- Weight: NOT scored in v1; cross-references logged for Phase-2 back-computation
- Friction: Aetheria arbitrates -> Jon escalates (enforced at agent permission
  layer, not in the store)
- No new fields. No new states. No new boards.
"""

from soveryn.platform.coordination.types import (
    CoordBoard,
    CoordinationError,
    CoordinationNode,
    CoordStatus,
    VALID_TRANSITIONS,
)
from soveryn.platform.coordination.store import CoordinationStore

__all__ = [
    "CoordBoard",
    "CoordStatus",
    "CoordinationError",
    "CoordinationNode",
    "CoordinationStore",
    "VALID_TRANSITIONS",
]
