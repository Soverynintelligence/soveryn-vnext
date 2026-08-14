"""Bookkeeping may never break the heartbeat.

Everything else in this file is secondary to that. `record_pulse` wraps
Aetheria's spontaneous initiation, so any way it can raise is a way the house
can lose her voice — and the failure would look exactly like the 2026-07-26
outage, where twenty-six hours of silence read as an agent choosing not to act
and was actually a dead pipe.

So the tests are ordered accordingly: first that the tick survives a registry
that is missing, unwritable, corrupt or stale; then that when the registry does
work, the pulse is recorded honestly.
"""
from __future__ import annotations

import sqlite3

import pytest

from soveryn.citizens.commissions import abandoned, for_citizen
from soveryn.citizens.pulse import record_pulse
from soveryn.citizens.registry import Citizen, connect, register

NOW = "2026-08-14T09:00:00Z"


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "citizens.db"
    with connect(path) as conn:
        register(conn, Citizen(id="aetheria", display_name="Aetheria"))
    return path


# ── the invariant ───────────────────────────────────────────────────────────

def test_the_tick_runs_when_there_is_no_registry_at_all(tmp_path):
    ran = []
    with record_pulse(tmp_path / "nope.db", "aetheria", "pulse",
                      worker="hb", now=NOW):
        ran.append(True)
    assert ran == [True]


def test_the_tick_runs_when_bookkeeping_is_switched_off(tmp_path):
    ran = []
    with record_pulse(None, "aetheria", "pulse", worker="hb", now=NOW) as cid:
        ran.append(cid)
    assert ran == [None]


def test_the_tick_runs_when_the_registry_file_is_corrupt(tmp_path):
    junk = tmp_path / "corrupt.db"
    junk.write_bytes(b"this is not a database")
    ran = []
    with record_pulse(junk, "aetheria", "pulse", worker="hb", now=NOW):
        ran.append(True)
    assert ran == [True]


def test_the_tick_runs_when_the_citizen_is_not_registered(tmp_path):
    """A foreign-key refusal must not become her silence."""
    path = tmp_path / "empty.db"
    with connect(path):
        pass
    ran = []
    with record_pulse(path, "aetheria", "pulse", worker="hb", now=NOW) as cid:
        ran.append(cid)
    assert ran == [None]


def test_the_tick_runs_when_closing_the_commission_fails(db_path, monkeypatch):
    from soveryn.citizens import pulse as pulse_mod

    def explode(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(pulse_mod.commissions, "complete", explode)
    ran = []
    with record_pulse(db_path, "aetheria", "pulse", worker="hb", now=NOW):
        ran.append(True)
    assert ran == [True]


# ── and when it works, it tells the truth ───────────────────────────────────

def test_a_completed_pulse_is_recorded_done_with_a_trace(db_path):
    with record_pulse(db_path, "aetheria", "heartbeat pulse",
                      worker="heartbeat", now=NOW, result_ref="log:tick-1"):
        pass
    with connect(db_path) as conn:
        (row,) = for_citizen(conn, "aetheria")
    assert row["state"] == "done"
    assert row["body"] == "heartbeat pulse"
    assert row["result_ref"] == "log:tick-1"
    assert row["claimed_by"] == "heartbeat"


def test_a_pulse_never_sits_in_queued_where_a_worker_can_steal_it(db_path):
    """The reproduced defect: enqueue+claim left a window for the drain worker.

    While the pulse is in flight the row must already be running+owned, and
    claim() must return None so the runtime cannot take it.
    """
    from soveryn.citizens import commissions

    with record_pulse(db_path, "aetheria", "heartbeat pulse",
                      worker="heartbeat", now=NOW) as cid:
        assert cid is not None
        with connect(db_path) as conn:
            row = commissions.get(conn, cid)
            assert row is not None
            assert row["state"] == "running"
            assert row["claimed_by"] == "heartbeat"
            # Nothing for the drain worker to take.
            assert commissions.claim(
                conn, "aetheria", worker="citizens-runtime", at=NOW
            ) is None
            assert commissions.for_citizen(
                conn, "aetheria", state="queued"
            ) == []


def test_a_pulse_that_raises_is_recorded_failed_and_the_error_propagates(db_path):
    class TickFailed(RuntimeError):
        pass

    with pytest.raises(TickFailed):
        with record_pulse(db_path, "aetheria", "pulse", worker="hb", now=NOW):
            raise TickFailed("vnext unreachable")

    with connect(db_path) as conn:
        (row,) = for_citizen(conn, "aetheria")
    assert row["state"] == "failed"
    assert "vnext unreachable" in row["error"]


def test_a_pulse_interrupted_by_shutdown_still_records_and_reraises(db_path):
    """SIGTERM during a tick must not look like a completed pulse."""
    with pytest.raises(KeyboardInterrupt):
        with record_pulse(db_path, "aetheria", "pulse", worker="hb", now=NOW):
            raise KeyboardInterrupt

    with connect(db_path) as conn:
        (row,) = for_citizen(conn, "aetheria")
    assert row["state"] == "failed"


def test_a_daemon_that_dies_mid_pulse_leaves_findable_work(db_path):
    """The 2026-07-26 shape: not a crash, a stall that nobody could see."""
    from soveryn.citizens import commissions

    with connect(db_path) as conn:
        commissions.enqueue(conn, "aetheria", "pulse", at=NOW)
        commissions.claim(conn, "aetheria", worker="hb", at=NOW)
        # process dies here — nothing completes it
        stalled = abandoned(conn, claimed_before="2026-08-14T10:00:00Z")
    assert len(stalled) == 1
    assert stalled[0]["claimed_by"] == "hb"


def test_pulses_do_not_accumulate_as_running(db_path):
    for i in range(5):
        with record_pulse(db_path, "aetheria", f"pulse {i}",
                          worker="hb", now=f"2026-08-14T09:{i:02d}:00Z"):
            pass
    with connect(db_path) as conn:
        rows = for_citizen(conn, "aetheria")
    assert len(rows) == 5
    assert {r["state"] for r in rows} == {"done"}
