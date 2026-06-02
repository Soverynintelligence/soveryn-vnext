"""Pure-function routing rules for CoordEvents.

The router decides which destination agents (if any) should be triggered
by a given event. Rules are encoded as a small explicit table per the
locked spec (no dynamic subscriptions in v1).

Hard rule: an event whose actor_agent matches a destination is NEVER
routed to that destination — agents don't trigger themselves.
"""

from __future__ import annotations

from soveryn.platform.coordination.events import CoordEvent, CoordEventKind
from soveryn.platform.coordination.types import CoordBoard, CoordStatus


def route(event: CoordEvent) -> tuple[str, ...]:
    """Return the tuple of destination agent names triggered by this event.

    Routing table (locked 2026-06-01 evening):

    - NODE_CREATED on Signal       -> aetheria (triage)
    - NODE_CREATED on Blueprint    -> aetheria (review for alignment, unless she was the actor)
    - PROMOTED to Blueprint        -> scotty (start spec'ing immediately)
    - PROMOTED to Friction         -> (none — Aetheria arbitration happens through chat, not webhook)
    - STATUS_CHANGED Blueprint Open->Refining   -> scotty (refine toward Ready)
    - STATUS_CHANGED Blueprint Refining->Ready  -> aetheria (review before user handoff)
    - BLOCK_ADDED on Blueprint     -> aetheria (arbitration territory)
    - ARCHIVED                     -> (none — terminal, lesson lives in lattice for recall)

    Self-routing is filtered out at the bottom (agents don't trigger
    themselves). Returns an empty tuple when no rule fires.
    """
    destinations: list[str] = []

    if event.kind == CoordEventKind.NODE_CREATED:
        board = event.payload.get("board")
        if board == CoordBoard.SIGNAL.value:
            destinations.append("aetheria")
        elif board == CoordBoard.BLUEPRINT.value:
            destinations.append("aetheria")

    elif event.kind == CoordEventKind.PROMOTED:
        target_board = event.payload.get("target_board")
        if target_board == CoordBoard.BLUEPRINT.value:
            destinations.append("scotty")

    elif event.kind == CoordEventKind.STATUS_CHANGED:
        # We only act on Blueprint transitions. The payload carries old/new.
        old_status = event.payload.get("old_status")
        new_status = event.payload.get("new_status")
        board = event.payload.get("board")
        if board == CoordBoard.BLUEPRINT.value:
            if (old_status == CoordStatus.OPEN.value
                    and new_status == CoordStatus.REFINING.value):
                destinations.append("scotty")
            elif (old_status == CoordStatus.REFINING.value
                    and new_status == CoordStatus.READY.value):
                destinations.append("aetheria")

    elif event.kind == CoordEventKind.BLOCK_ADDED:
        destinations.append("aetheria")

    elif event.kind == CoordEventKind.ARCHIVED:
        # Terminal; lesson now lives in lattice for recall but no auto-trigger.
        pass

    # Hard rule: agents don't trigger themselves.
    return tuple(d for d in destinations if d != event.actor_agent)
