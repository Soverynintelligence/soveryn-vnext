"""Tests for the heartbeat daemon's salience hook.

Tests the `_gather_salience` module-level helper directly — that's the
entire seam between the heartbeat tick and the salience engine. The
daemon's run loop (signal handlers, sleeps) isn't exercised here; those
are integration-test territory and orthogonal to the salience wiring.

Per Task 6 of the Salience Engine plan (2026-06-08).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from soveryn.agents.heartbeat.daemon import (
    DEFAULT_SALIENCE_DB,
    HeartbeatDaemon,
    _build_daemon_from_env,
    _gather_salience,
)
from soveryn.agents.heartbeat.trigger import HeartbeatConfig
from soveryn.platform.salience.markers import MarkerHit
from soveryn.platform.salience.store import (
    create_buffer_table,
    insert_candidate,
)


# ─── Helpers ────────────────────────────────────────────────────────────────


def _hard_lock_hit() -> MarkerHit:
    return MarkerHit(category="hard_lock", marker="locked", weight=4)


def _seed_one_pending(db: Path, *, head: str = "The plan is locked.") -> str:
    """Create the table, insert one Hard Lock candidate, return its id."""
    create_buffer_table(db)
    return insert_candidate(
        db,
        session_id="s1",
        turn_rowid=1,
        turn_role="user",
        turn_content_head=head,
        markers=[_hard_lock_hit()],
        heuristic_score=4.0,
        novelty_score=None,
    )


def _backdate_detected_at(db: Path, *, candidate_id: str, iso_ts: str) -> None:
    """Mutate detected_at directly — production code never does this, but
    tests need to simulate aged rows without time.sleep."""
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "UPDATE salience_buffer SET detected_at = ? WHERE id = ?",
            (iso_ts, candidate_id),
        )


def _minimal_config() -> HeartbeatConfig:
    """The frozen dataclass takes positional fields; from_env honors env
    but we don't want test pollution from real env vars here."""
    return HeartbeatConfig(
        enabled=True,
        dry_run=True,
        interval_seconds=1800,
        backoff_seconds=600,
        quiet_hours="",
    )


# ─── _gather_salience direct tests ──────────────────────────────────────────


def test_gather_salience_returns_section_for_pending_candidate(tmp_path):
    db = tmp_path / "salience.db"
    cand_id = _seed_one_pending(db, head="The plan is locked.")
    out = _gather_salience(db, since=datetime.now() - timedelta(hours=1))
    assert out  # non-empty
    assert "1 moment" in out
    assert "locked" in out
    assert cand_id in out


def test_gather_salience_returns_empty_when_no_pending(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)  # empty table
    out = _gather_salience(db, since=datetime.now() - timedelta(hours=1))
    assert out == ""


def test_gather_salience_decays_old_pending_first(tmp_path):
    db = tmp_path / "salience.db"
    cand_id = _seed_one_pending(db)
    # Backdate to 20 days ago — past the 14-day decay cutoff.
    old_ts = (datetime.now() - timedelta(days=20)).isoformat()
    _backdate_detected_at(db, candidate_id=cand_id, iso_ts=old_ts)

    # Wide since window so the row WOULD be returned if it were still pending.
    out = _gather_salience(db, since=datetime.now() - timedelta(days=30))
    assert out == ""

    # Direct probe — decay must have flipped status, not just suppressed read.
    with sqlite3.connect(str(db)) as con:
        row = con.execute(
            "SELECT status FROM salience_buffer WHERE id = ?",
            (cand_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == "decayed"


def test_gather_salience_swallows_missing_db_path(tmp_path):
    """Best-effort contract: a missing DB / missing schema must not raise.
    The heartbeat tick continues with an empty section."""
    # Path to a nested file we never create — opening it as sqlite3 will
    # fail at the schema-less read (no salience_buffer table).
    missing = tmp_path / "does" / "not" / "exist.db"
    # Don't create_buffer_table, don't mkdir parents — the helper must cope.
    out = _gather_salience(missing, since=datetime.now() - timedelta(hours=1))
    assert out == ""


def test_gather_salience_respects_since_window(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    # Recent candidate (now).
    recent_id = insert_candidate(
        db,
        session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="locked in fresh",
        markers=[_hard_lock_hit()],
        heuristic_score=4.0, novelty_score=None,
    )
    # Older candidate (backdated to 2 hours ago).
    old_id = insert_candidate(
        db,
        session_id="s1", turn_rowid=2, turn_role="user",
        turn_content_head="locked in stale",
        markers=[_hard_lock_hit()],
        heuristic_score=4.0, novelty_score=None,
    )
    old_ts = (datetime.now() - timedelta(hours=2)).isoformat()
    _backdate_detected_at(db, candidate_id=old_id, iso_ts=old_ts)

    out = _gather_salience(db, since=datetime.now() - timedelta(hours=1))
    assert out  # non-empty
    assert "1 moment" in out         # only the recent one
    assert "1 moments" not in out    # not plural
    assert recent_id in out
    assert old_id not in out


# ─── Default constant + daemon constructor wiring ───────────────────────────


def test_default_salience_db_constant_is_under_soveryn_memory():
    """Smoke: the production default is the canonical data_root memory path."""
    assert DEFAULT_SALIENCE_DB.name == "salience_vnext.db"
    assert DEFAULT_SALIENCE_DB.parent.name == "memory"


def test_heartbeat_daemon_takes_salience_db_kwarg(tmp_path):
    """Constructor wiring: salience_db kwarg lands on the instance as a
    Path. We don't call run() — only the construction surface."""
    target = tmp_path / "anywhere.db"
    daemon = HeartbeatDaemon(_minimal_config(), salience_db=target)
    assert daemon.salience_db == Path(target)


def test_heartbeat_daemon_default_salience_db_when_kwarg_omitted():
    daemon = HeartbeatDaemon(_minimal_config())
    assert daemon.salience_db == DEFAULT_SALIENCE_DB


# ─── Env-var override (via extracted helper) ────────────────────────────────


def test_env_var_override_is_picked_up(tmp_path, monkeypatch):
    """SOVERYN_SALIENCE_DB env var overrides the default at construction
    time. Tested via the extracted _build_daemon_from_env helper so we
    don't have to enter the run loop."""
    target = tmp_path / "override.db"
    monkeypatch.setenv("SOVERYN_SALIENCE_DB", str(target))
    # Keep the daemon from trying anything outside construction.
    monkeypatch.setenv("SOVERYN_HEARTBEAT_ENABLED", "false")
    daemon = _build_daemon_from_env()
    assert daemon.salience_db == Path(target)


def test_env_var_absent_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("SOVERYN_SALIENCE_DB", raising=False)
    monkeypatch.setenv("SOVERYN_HEARTBEAT_ENABLED", "false")
    daemon = _build_daemon_from_env()
    assert daemon.salience_db == DEFAULT_SALIENCE_DB
