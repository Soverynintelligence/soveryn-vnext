"""Pure-function tests for the CoordEvent routing table.

The bulk of routing coverage lives in test_coordination_webhooks.py
alongside the dispatcher tests. This file holds rules added by the
direct-agent-communication arc (spec: DAC, 2026-06-05).
"""


def test_needs_direction_event_routes_to_aetheria():
    """Vett or Scotty raising NEEDS_DIRECTION pings Aetheria."""
    from soveryn.platform.coordination.events import CoordEvent, CoordEventKind
    from soveryn.platform.coordination.routing import route
    event = CoordEvent(
        id="e1", kind=CoordEventKind.NEEDS_DIRECTION,
        node_id="node-1", actor_agent="scotty",
        timestamp="2026-06-05T12:00:00",
        payload={"context_summary": "stuck",
                 "options_considered": ["a", "b"]},
        chain_depth=0,
    )
    assert route(event) == ("aetheria",)


def test_needs_direction_from_vett_also_routes_to_aetheria():
    """Vett can raise NEEDS_DIRECTION too."""
    from soveryn.platform.coordination.events import CoordEvent, CoordEventKind
    from soveryn.platform.coordination.routing import route
    event = CoordEvent(
        id="e1", kind=CoordEventKind.NEEDS_DIRECTION,
        node_id="node-1", actor_agent="vett",
        timestamp="2026-06-05T12:00:00",
        payload={}, chain_depth=0,
    )
    assert route(event) == ("aetheria",)


def test_aetheria_cannot_raise_needs_direction_to_herself():
    """Self-filter — if Aetheria is somehow the actor, no routing.
    (She has no request_direction tool registered, but defense in depth.)"""
    from soveryn.platform.coordination.events import CoordEvent, CoordEventKind
    from soveryn.platform.coordination.routing import route
    event = CoordEvent(
        id="e1", kind=CoordEventKind.NEEDS_DIRECTION,
        node_id="node-1", actor_agent="aetheria",
        timestamp="2026-06-05T12:00:00", payload={}, chain_depth=0,
    )
    assert route(event) == ()
