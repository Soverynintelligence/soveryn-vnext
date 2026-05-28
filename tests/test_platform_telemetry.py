"""Tests for telemetry log/query persistence."""

import json
import sqlite3

import pytest

from soveryn.platform.telemetry import TelemetryError, TelemetryStore, log, query


def test_log_and_query_round_trip_with_module_api(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_TELEMETRY_DIR", str(tmp_path / "telemetry"))

    event = log(
        source="platform.tools.registry",
        event_type="tool.invoked",
        level="info",
        payload={"tool_name": "echo"},
    )
    rows = query({"event_type": "tool.invoked"}, limit=10)

    assert rows == (event,)
    assert rows[0].source == "platform.tools.registry"
    assert rows[0].payload == {"tool_name": "echo"}


def test_log_persists_to_jsonl_and_sqlite_mirror(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry")

    event = store.log(source="ares", event_type="anomaly.recorded", payload={"severity": "low"})

    jsonl_lines = store.jsonl_path.read_text().splitlines()
    assert len(jsonl_lines) == 1
    assert json.loads(jsonl_lines[0])["source"] == "ares"
    with sqlite3.connect(store.sqlite_path) as conn:
        row = conn.execute("SELECT source, event_type, level, payload FROM telemetry").fetchone()
    assert row[0] == event.source
    assert row[1] == event.event_type
    assert row[2] == event.level
    assert json.loads(row[3]) == event.payload


def test_rapid_log_calls_all_land_queryable_in_order(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry")

    events = [
        store.log(source="ares", event_type="anomaly.recorded", payload={"i": i})
        for i in range(50)
    ]

    rows = store.query({"source": "ares"}, limit=100)
    assert rows == tuple(events)
    assert [row.payload["i"] for row in rows] == list(range(50))


def test_query_level_filter_returns_only_requested_level(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry")
    store.log(source="ares", event_type="ok", level="info", payload={})
    error_event = store.log(source="ares", event_type="bad", level="error", payload={"x": 1})

    assert store.query({"level": "error"}, limit=10) == (error_event,)


def test_query_source_event_type_and_time_filters(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry")
    first = store.log(source="ares", event_type="anomaly.recorded", payload={"i": 1})
    second = store.log(source="platform.tools.registry", event_type="tool.invoked", payload={"i": 2})
    third = store.log(source="ares", event_type="anomaly.recorded", payload={"i": 3})

    rows = store.query({
        "source": "ares",
        "event_type": "anomaly.recorded",
        "since": first.created_at,
        "until": third.created_at,
    }, limit=10)

    assert rows == (first, third)
    assert second not in rows


def test_invalid_level_and_non_json_payload_are_rejected(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry")

    with pytest.raises(TelemetryError, match="level"):
        store.log(source="ares", event_type="x", level="audit", payload={})
    with pytest.raises(TelemetryError, match="JSON-serializable"):
        store.log(source="ares", event_type="x", payload={"bad": object()})


def test_unknown_query_filter_is_rejected(tmp_path):
    store = TelemetryStore(tmp_path / "telemetry")

    with pytest.raises(TelemetryError, match="unknown telemetry query filters"):
        store.query({"agent": "ares"}, limit=10)
