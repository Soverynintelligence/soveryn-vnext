"""Tests for the platform event bus interface."""

import sqlite3

import pytest

from soveryn.platform.bus import (
    BusError,
    InMemoryBus,
    KNOWN_EVENT_TYPES,
    SQLiteBus,
)


def test_declares_required_event_types():
    assert {
        "chat.message.received",
        "chat.response.outbound",
        "anomaly.detected",
        "tool.invoked",
    }.issubset(KNOWN_EVENT_TYPES)


def test_in_memory_bus_publish_and_subscribe_by_cursor():
    bus = InMemoryBus()
    first = bus.publish("chat.message.received", {"message": "hi"}, actor="aetheria")
    second = bus.publish("tool.invoked", {"tool": "echo"}, actor="scotty")

    assert first.id == 1
    assert second.id == 2
    assert bus.subscribe(["chat.message.received"], cursor=0) == (first,)
    assert bus.subscribe(["chat.message.received", "tool.invoked"], cursor=1) == (second,)


def test_in_memory_bus_limit_preserves_id_order():
    bus = InMemoryBus()
    events = [
        bus.publish("anomaly.detected", {"i": i}, actor="ares")
        for i in range(3)
    ]

    assert bus.subscribe(["anomaly.detected"], cursor=0, limit=2) == tuple(events[:2])


def test_unknown_event_type_is_rejected():
    bus = InMemoryBus()

    with pytest.raises(BusError, match="unknown event_type"):
        bus.publish("unknown.event", {}, actor="test")


def test_sqlite_bus_persists_events_across_instances(tmp_path):
    db = tmp_path / "bus.db"
    bus = SQLiteBus(db)
    published = bus.publish("chat.response.outbound", {"content": "hello"}, actor="aetheria")

    reopened = SQLiteBus(db)
    events = reopened.subscribe(["chat.response.outbound"], cursor=0)

    assert len(events) == 1
    assert events[0].id == published.id
    assert events[0].event_type == "chat.response.outbound"
    assert events[0].payload == {"content": "hello"}
    assert events[0].actor == "aetheria"


def test_sqlite_bus_uses_wal_mode(tmp_path):
    db = tmp_path / "bus.db"
    SQLiteBus(db)

    with sqlite3.connect(db) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert mode.lower() == "wal"


def test_sqlite_bus_rejects_non_json_payload(tmp_path):
    bus = SQLiteBus(tmp_path / "bus.db")

    with pytest.raises(BusError, match="JSON-serializable"):
        bus.publish("tool.invoked", {"bad": object()}, actor="scotty")


def test_sqlite_bus_empty_subscription_returns_empty_tuple(tmp_path):
    bus = SQLiteBus(tmp_path / "bus.db")
    bus.publish("anomaly.detected", {"kind": "disk"}, actor="ares")

    assert bus.subscribe([], cursor=0) == ()

def test_sqlite_bus_cross_restart_durability_for_ares_events(tmp_path):
    db = tmp_path / "bus.db"
    bus = SQLiteBus(db)
    published = (
        bus.publish("anomaly.detected", {"type": "disk", "severity": "low"}, actor="ares"),
        bus.publish("tool.invoked", {"tool_name": "echo", "ok": True}, actor="scotty"),
        bus.publish("anomaly.detected", {"type": "thermal", "severity": "medium"}, actor="ares"),
    )

    del bus
    reopened = SQLiteBus(db)
    events = reopened.subscribe(["anomaly.detected", "tool.invoked"], cursor=0)

    assert events == published
    assert [event.id for event in events] == sorted(event.id for event in events)
    assert events[0].payload == {"type": "disk", "severity": "low"}
    assert events[2].payload == {"type": "thermal", "severity": "medium"}


def test_sqlite_bus_independent_callers_track_their_own_cursors(tmp_path):
    bus = SQLiteBus(tmp_path / "bus.db")
    first = bus.publish("anomaly.detected", {"i": 1}, actor="ares")
    second = bus.publish("anomaly.detected", {"i": 2}, actor="ares")
    third = bus.publish("anomaly.detected", {"i": 3}, actor="ares")

    caller_a = bus.subscribe(["anomaly.detected"], cursor=0)
    caller_b = bus.subscribe(["anomaly.detected"], cursor=first.id)
    caller_a_again = bus.subscribe(["anomaly.detected"], cursor=second.id)

    assert caller_a == (first, second, third)
    assert caller_b == (second, third)
    assert caller_a_again == (third,)


def test_sqlite_bus_rejects_unknown_event_type_on_publish(tmp_path):
    bus = SQLiteBus(tmp_path / "bus.db")

    with pytest.raises(BusError, match="unknown event_type"):
        bus.publish("unknown.event", {}, actor="ares")
