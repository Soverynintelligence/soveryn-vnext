"""Telemetry retention tests — the 6.3 GB hole (2026-09-24).

telemetry.db + telemetry.jsonl grew forever; a disk-full event would take
down Messages, lattice, delegation and Ares simultaneously. Pins: prune by
age, jsonl rotation archives instead of deleting, housekeeping never breaks
a log write.
"""
from __future__ import annotations

import gzip

import pytest

from soveryn.platform.telemetry.api import TelemetryStore


@pytest.fixture()
def store(tmp_path):
    return TelemetryStore(telemetry_dir=tmp_path / "telemetry")


def _insert_at(store: TelemetryStore, created_at: str, source: str = "t") -> None:
    with store._conn() as conn:
        conn.execute(
            "INSERT INTO telemetry (source, event_type, level, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, "test.event", "info", "{}", created_at),
        )


def test_prune_deletes_only_old_rows(store):
    _insert_at(store, "2026-01-01T00:00:00+00:00")   # ancient
    _insert_at(store, "2099-01-01T00:00:00+00:00")   # future-dated
    removed = store.prune(days=30)
    assert removed == 1
    remaining = store.query(limit=10)
    assert len(remaining) == 1
    assert remaining[0].created_at.startswith("2099-01-01")


def test_rotation_archives_and_starts_fresh(store, monkeypatch):
    monkeypatch.setattr(store, "ROTATE_BYTES", 64)
    monkeypatch.setattr(store, "ROTATE_KEEP", 1)
    for i in range(5):
        store.log(source="t", event_type="e", payload={"i": i, "pad": "x" * 40})
    assert store.jsonl_path.stat().st_size < 64  # fresh segment after rotation
    archives = list(store.telemetry_dir.glob("telemetry-*.jsonl.gz"))
    assert len(archives) == 1
    with gzip.open(archives[0], "rt") as fh:
        assert "e" in fh.read()


def test_housekeep_swallows_db_errors(store, monkeypatch):
    """Retention must never break a log write — the 6.3 GB lesson's sibling."""
    def boom(days):
        raise RuntimeError("db busy")

    monkeypatch.setattr(store, "prune", boom)
    TelemetryStore._last_housekeep = 0.0  # force the hourly gate open
    try:
        event = store.log(source="t", event_type="e", payload={})
        assert event.source == "t"
    finally:
        TelemetryStore._last_housekeep = 0.0


def test_hourly_gate_limits_housekeeping(store, monkeypatch):
    calls = []
    monkeypatch.setattr(store, "prune", lambda days: calls.append(days) or 0)
    monkeypatch.setattr(store, "_rotate_jsonl", lambda: None)
    TelemetryStore._last_housekeep = 0.0
    store.log(source="t", event_type="e", payload={})
    store.log(source="t", event_type="e", payload={})
    assert len(calls) == 1  # second write within the hour skips housekeeping
    TelemetryStore._last_housekeep = 0.0
