"""Tests for soveryn.platform.coordination.tools — direct invocation of
the tool handlers. Mirrors the pattern used elsewhere for tool tests:
bypass the registry, call handler directly with a dict of args.
"""

from __future__ import annotations

import pytest

from soveryn.platform.coordination.events import (
    CoordEventKind,
    InMemoryEventBus,
)
from soveryn.platform.coordination.store import CoordinationStore
from soveryn.platform.coordination.types import CoordBoard
from soveryn.platform.coordination.tools import build_request_direction_tool
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.tools.registry import ToolArgError


@pytest.fixture
def coord_store(tmp_path):
    # CoordinationStore extends the lattice schema; init LatticeStore first
    # so the nodes/coord_references tables exist.
    db_path = tmp_path / "coord.db"
    LatticeStore(db_path)
    return CoordinationStore(db_path)


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


def test_request_direction_emits_needs_direction_event(coord_store, event_bus):
    """Tool publishes a NEEDS_DIRECTION event with the brief + options."""
    # Pre-create a coord node Scotty is referring to. The store's
    # default NullEventBus swallows the NODE_CREATED emission, so
    # event_bus stays clean until the tool runs.
    node = coord_store.create_node(
        board=CoordBoard.BLUEPRINT,
        owner="scotty",
        content="port the foo module",
    )

    tool = build_request_direction_tool(
        store=coord_store, event_bus=event_bus, owner_agent="scotty",
    )
    result = tool.handler({
        "node_id": node.id,
        "context_summary": "Two approaches diverge; need your call",
        "options_considered": ["full rewrite", "incremental"],
    })

    assert result["needs_direction_event_id"]
    events = event_bus.drain()
    assert len(events) == 1
    assert events[0].kind == CoordEventKind.NEEDS_DIRECTION
    assert events[0].node_id == node.id
    assert events[0].actor_agent == "scotty"
    assert events[0].payload["context_summary"] == "Two approaches diverge; need your call"
    assert events[0].payload["options_considered"] == ["full rewrite", "incremental"]
    assert events[0].payload["requester_agent"] == "scotty"


def test_request_direction_rejects_nonexistent_node(coord_store, event_bus):
    """node_id must point to a real coord node — returns structured error."""
    tool = build_request_direction_tool(
        store=coord_store, event_bus=event_bus, owner_agent="scotty",
    )
    result = tool.handler({
        "node_id": "nonexistent-uuid",
        "context_summary": "x",
        "options_considered": ["a"],
    })
    assert result.get("error") == "unknown_node"
    # No event emitted on rejection
    assert event_bus.drain() == []


def test_request_direction_requires_at_least_one_option(coord_store, event_bus):
    """Empty options is a schema violation — if you have no options, you
    don't have a direction question, you have a panic."""
    node = coord_store.create_node(
        board=CoordBoard.BLUEPRINT, owner="scotty", content="x",
    )
    tool = build_request_direction_tool(
        store=coord_store, event_bus=event_bus, owner_agent="scotty",
    )
    with pytest.raises(ToolArgError, match="options_considered"):
        tool.handler({
            "node_id": node.id,
            "context_summary": "stuck",
            "options_considered": [],
        })


def test_request_direction_rejects_empty_context_summary(coord_store, event_bus):
    """A direction request needs context."""
    node = coord_store.create_node(
        board=CoordBoard.BLUEPRINT, owner="scotty", content="x",
    )
    tool = build_request_direction_tool(
        store=coord_store, event_bus=event_bus, owner_agent="scotty",
    )
    with pytest.raises(ToolArgError, match="context_summary"):
        tool.handler({
            "node_id": node.id,
            "context_summary": "   ",
            "options_considered": ["a"],
        })


def test_request_direction_for_vett(coord_store, event_bus):
    """Same tool, Vett owner — actor_agent reflects the owner."""
    node = coord_store.create_node(
        board=CoordBoard.SIGNAL, owner="vett", content="research lead",
    )
    tool = build_request_direction_tool(
        store=coord_store, event_bus=event_bus, owner_agent="vett",
    )
    tool.handler({
        "node_id": node.id,
        "context_summary": "Lead has conflicting hits",
        "options_considered": ["validate primary", "pivot"],
    })
    events = event_bus.drain()
    assert len(events) == 1
    assert events[0].actor_agent == "vett"
    assert events[0].payload["requester_agent"] == "vett"
