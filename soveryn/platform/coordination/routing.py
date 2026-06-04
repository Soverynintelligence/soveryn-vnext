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

    Routing table (locked 2026-06-01; refined 2026-06-04 for owner-aware
    Blueprint routing per the Vett patrol spec):

    - NODE_CREATED on Signal       -> aetheria (triage)
    - NODE_CREATED on Blueprint    -> aetheria (review) + owner (start)
                                       — the self-filter drops aetheria when
                                       she is the owner (and the actor)
    - PROMOTED to Blueprint        -> target_owner (the agent the promoter
                                       assigned the work to). Without an
                                       explicit owner in payload, routes
                                       nowhere — the universal-to-scotty
                                       hardcode was the bug being fixed
    - PROMOTED to Friction         -> (none — Aetheria arbitration happens through chat, not webhook)
    - STATUS_CHANGED Blueprint Open->Refining   -> scotty (refine toward Ready)
    - STATUS_CHANGED Blueprint Refining->Ready  -> aetheria (review before user handoff)
    - BLOCK_ADDED on Blueprint     -> aetheria (arbitration territory)
    - ARCHIVED                     -> (none — terminal, lesson lives in lattice for recall)

    Destinations are deduped (preserving first-seen order) and the actor
    is filtered out. Returns an empty tuple when no rule fires.
    """
    destinations: list[str] = []

    if event.kind == CoordEventKind.NODE_CREATED:
        board = event.payload.get("board")
        if board == CoordBoard.SIGNAL.value:
            destinations.append("aetheria")
        elif board == CoordBoard.BLUEPRINT.value:
            destinations.append("aetheria")
            owner = event.payload.get("owner")
            if isinstance(owner, str) and owner.strip():
                destinations.append(owner.strip())

    elif event.kind == CoordEventKind.PROMOTED:
        target_board = event.payload.get("target_board")
        if target_board == CoordBoard.BLUEPRINT.value:
            target_owner = event.payload.get("target_owner")
            if isinstance(target_owner, str) and target_owner.strip():
                destinations.append(target_owner.strip())

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

    # Hard rule: agents don't trigger themselves. Also dedupe — under
    # owner-aware routing, the same agent can appear twice (e.g. an
    # NODE_CREATED on Blueprint where the owner is aetheria adds her
    # both as reviewer and owner). Preserve first-seen order so the
    # router stays deterministic for tests.
    seen: list[str] = []
    for d in destinations:
        if d != event.actor_agent and d not in seen:
            seen.append(d)
    return tuple(seen)
