"""Tests for the dream daemon loop.

Covers: spin-bug resistance under consecutive skipped ticks (matches the
heartbeat/patrol regression guard), dry-run mode writes only the audit
row, and end-to-end run uses the cognition orchestrator.
"""

import sqlite3
import threading
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from soveryn.agents.dream.config import DreamConfig
from soveryn.agents.dream.daemon import DreamDaemon
from soveryn.agents.dream.cognition import CognitionResult
from soveryn.platform.lattice.legacy import LatticeStore


def _config(**kw) -> DreamConfig:
    base = dict(
        enabled=True, dry_run=True, quiet_hours="00:00-23:59",
        activity_backoff_seconds=1800, nodes_per_run=300,
        max_internal_iterations=3,
        cognition_url="http://x", cognition_timeout_seconds=10,
    )
    base.update(kw)
    return DreamConfig(**base)


@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    return db


@pytest.fixture
def conv_db(tmp_path):
    return tmp_path / "conv.db"  # daemon reads from this for activity check


def test_daemon_does_not_spin_on_consecutive_skipped_ticks(lattice_db, conv_db, tmp_path):
    """Regression: matches the heartbeat 0fb715b + patrol spin-bug guard.
    With enabled=False every tick skips; sleep math must not collapse."""
    config = _config(enabled=False)  # forces DISABLED skip on every tick
    daemon = DreamDaemon(
        config, lattice_db=lattice_db, conv_db=conv_db,
        tick_interval_seconds=2,
    )
    t = threading.Thread(target=daemon.run, daemon=True)
    t.start()
    time.sleep(1.0)
    daemon._stop = True
    t.join(timeout=5)
    with sqlite3.connect(str(lattice_db)) as con:
        row_count = con.execute(
            "SELECT COUNT(*) FROM dream_log"
        ).fetchone()[0]
    # Without the fix this loop emits hundreds of rows; with the fix and
    # interval=2s we should see <=5 in ~1s.
    assert row_count <= 5, f"daemon emitted {row_count} log rows in ~1s — spin bug regressed"


def test_daemon_dry_run_writes_only_audit_row(lattice_db, conv_db, tmp_path):
    """Eligible dry-run tick writes a dream_log row with dry_run=1, and
    skips the cognition call + reflection / edge writes."""
    # Seed a node so "nothing_to_dream_about" gate passes
    with sqlite3.connect(str(lattice_db)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at) "
            "VALUES ('n-seed', 'memory', 'lattice', 'aetheria', 'seed', "
            "0.5, 0.5, 0, ?, ?)",
            (datetime.now().isoformat(), datetime.now().isoformat()),
        )
    config = _config(dry_run=True)
    daemon = DreamDaemon(
        config, lattice_db=lattice_db, conv_db=conv_db,
        tick_interval_seconds=999999,  # only one tick will run before stop
    )
    with patch("soveryn.agents.dream.daemon.run_three_pass") as mock_three_pass:
        daemon._do_tick(now=datetime.now())
    # Cognition is NOT called in dry-run
    mock_three_pass.assert_not_called()
    with sqlite3.connect(str(lattice_db)) as con:
        log_rows = con.execute(
            "SELECT dry_run FROM dream_log"
        ).fetchall()
        dream_nodes = con.execute(
            "SELECT COUNT(*) FROM nodes WHERE layer = 'dream'"
        ).fetchone()[0]
    assert len(log_rows) == 1
    assert log_rows[0][0] == 1  # dry_run marker
    assert dream_nodes == 0


def test_daemon_live_run_invokes_three_pass_and_writes_outputs(lattice_db, conv_db, tmp_path):
    """Live (non-dry-run) tick calls run_three_pass and writes outputs."""
    with sqlite3.connect(str(lattice_db)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at) "
            "VALUES ('n-seed', 'memory', 'lattice', 'aetheria', 'seed', "
            "0.5, 0.5, 0, ?, ?)",
            (datetime.now().isoformat(), datetime.now().isoformat()),
        )
    config = _config(dry_run=False)
    daemon = DreamDaemon(
        config, lattice_db=lattice_db, conv_db=conv_db,
        tick_interval_seconds=999999,
    )
    fake_result = CognitionResult(
        iterations_completed=3,
        associations="assoc",
        contradictions="contra",
        synthesis="[node:n-seed] reflection content",
        loop_health=1.0,
        error=None,
    )
    with patch(
        "soveryn.agents.dream.daemon.run_three_pass",
        return_value=fake_result,
    ):
        daemon._do_tick(now=datetime.now())
    with sqlite3.connect(str(lattice_db)) as con:
        dream_nodes = con.execute(
            "SELECT COUNT(*) FROM nodes WHERE layer = 'dream'"
        ).fetchone()[0]
        log_row = con.execute(
            "SELECT dry_run, loop_health FROM dream_log LIMIT 1"
        ).fetchone()
    assert dream_nodes == 1
    assert log_row[0] == 0  # dry_run marker NOT set
    assert log_row[1] == 1.0
