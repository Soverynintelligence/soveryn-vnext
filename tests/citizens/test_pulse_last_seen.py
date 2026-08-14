"""A completed heartbeat pulse advances last_seen (Phase 3)."""
from __future__ import annotations

from soveryn.citizens.pulse import record_pulse
from soveryn.citizens.registry import Citizen, connect, register, status_of


def test_successful_pulse_observes_present_and_sets_last_seen(tmp_path):
    db = tmp_path / "citizens.db"
    with connect(db) as conn:
        register(conn, Citizen(id="aetheria", display_name="Aetheria"))
        assert status_of(conn, "aetheria") == "unobserved"

    with record_pulse(
        db, "aetheria", "heartbeat pulse",
        worker="heartbeat", now="2026-08-14T12:00:00Z",
    ):
        pass

    with connect(db) as conn:
        assert status_of(conn, "aetheria") == "resident"
        row = conn.execute(
            "SELECT last_seen_at FROM citizens WHERE id = 'aetheria'"
        ).fetchone()
        assert row["last_seen_at"] == "2026-08-14T12:00:00Z"
