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


def test_daemon_does_not_spin_on_consecutive_eligible_ticks(lattice_db, conv_db, tmp_path):
    """Regression: matches the heartbeat 0fb715b + patrol spin-bug guard.

    Original version used enabled=False which made every tick skip — but
    skipped ticks DON'T write to dream_log, so the assertion was vacuous.
    Rewritten 2026-06-05 per final code review: mock evaluate_tick to
    always return eligible, run dry-run (so writes happen but no cognition
    HTTP). With tick_interval_seconds=2 and ~1s wall-time, we should see
    at most a couple of ticks. Without the spin bug, sleep math correctly
    waits between ticks; with the bug, sleep_target stays in the past and
    the loop fires hundreds of times per second.
    """
    # Seed a node so the briefing has content (dry-run still gathers it).
    with sqlite3.connect(str(lattice_db)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at) "
            "VALUES ('n-seed', 'memory', 'lattice', 'aetheria', 'seed', "
            "0.5, 0.5, 0, ?, ?)",
            (datetime.now().isoformat(), datetime.now().isoformat()),
        )
    from soveryn.agents.dream.trigger import TickEligibility
    config = _config(dry_run=True)
    daemon = DreamDaemon(
        config, lattice_db=lattice_db, conv_db=conv_db,
        tick_interval_seconds=2,
    )
    with patch(
        "soveryn.agents.dream.daemon.evaluate_tick",
        return_value=TickEligibility(eligible=True, skip_reason=None),
    ):
        t = threading.Thread(target=daemon.run, daemon=True)
        t.start()
        time.sleep(1.0)
        daemon._stop = True
        t.join(timeout=5)
    with sqlite3.connect(str(lattice_db)) as con:
        row_count = con.execute(
            "SELECT COUNT(*) FROM dream_log"
        ).fetchone()[0]
    # Without spin bug + interval=2s + wall=1s: expect 1 tick (the first
    # iteration, before sleep). With spin bug: hundreds/thousands of rows.
    assert row_count <= 3, (
        f"daemon emitted {row_count} dream_log rows in ~1s with "
        f"interval=2s — spin bug regressed"
    )


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


# ─── 2026-06-08 fix: input gate counts conv turns + lattice nodes ──────────


def _seed_conversation_meta(conv_db_path, *, session_id, agent, title,
                            ts="2026-06-08T01:00:00"):
    """Seed a conversation_meta row + matching session row in the
    same shape ConversationStore.new_session produces."""
    import sqlite3
    # Ensure the schema exists (in case the test conv_db is bare)
    from soveryn.memory.conversation_store import ConversationStore
    ConversationStore(conv_db_path)
    with sqlite3.connect(str(conv_db_path)) as con:
        con.execute(
            "INSERT OR IGNORE INTO conversation_meta "
            "(session_id, agent, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, agent, title, ts, ts),
        )


def _seed_conversation_turn(conv_db_path, *, session_id, agent, role,
                            content, ts):
    """Seed a single conversation turn row."""
    import sqlite3
    with sqlite3.connect(str(conv_db_path)) as con:
        con.execute(
            "INSERT INTO conversations "
            "(session_id, agent, role, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, agent, role, content, ts),
        )


def test_new_conv_turn_count_excludes_heartbeat_signal_patrol(
    lattice_db, conv_db,
):
    """Activity from daemon-driven sessions ([heartbeat], [signal], [patrol],
    [webhook]) does NOT count — those are autonomous polling, not the
    relational input the dream should synthesize."""
    config = _config()
    daemon = DreamDaemon(config, lattice_db=lattice_db, conv_db=conv_db)
    # Seed five sessions: one direct chat (counts), four daemon-driven (don't)
    for sid, title in [
        ("chat-real", None),               # null title = direct chat
        ("hb", "[heartbeat] aetheria"),
        ("sig", "[signal] +15555550100"),
        ("pat", "[patrol] vett"),
        ("wh", "[webhook] aetheria"),
    ]:
        _seed_conversation_meta(conv_db, session_id=sid, agent="aetheria",
                                title=title)
    # 2 turns in the direct chat, 5 in each daemon session
    for i in range(2):
        _seed_conversation_turn(conv_db, session_id="chat-real",
                                agent="aetheria", role="user",
                                content="hi", ts=f"2026-06-08T01:{i:02d}:00")
    for sid in ("hb", "sig", "pat", "wh"):
        for i in range(5):
            _seed_conversation_turn(conv_db, session_id=sid,
                                    agent="aetheria", role="user",
                                    content="auto",
                                    ts=f"2026-06-08T01:{i:02d}:00")
    count = daemon._new_conv_turn_count_since(None)
    assert count == 2, f"expected 2 (direct chat only), got {count}"


def test_new_conv_turn_count_respects_since_cutoff(lattice_db, conv_db):
    config = _config()
    daemon = DreamDaemon(config, lattice_db=lattice_db, conv_db=conv_db)
    _seed_conversation_meta(conv_db, session_id="s1", agent="aetheria",
                            title=None)
    _seed_conversation_turn(conv_db, session_id="s1", agent="aetheria",
                            role="user", content="old",
                            ts="2026-06-07T20:00:00")
    _seed_conversation_turn(conv_db, session_id="s1", agent="aetheria",
                            role="user", content="newer",
                            ts="2026-06-08T01:00:00")
    cutoff = datetime(2026, 6, 7, 23, 0, 0)
    count = daemon._new_conv_turn_count_since(cutoff)
    assert count == 1  # only the 'newer' turn


def test_new_input_count_combines_lattice_and_conv(lattice_db, conv_db):
    """The gate the daemon uses: lattice nodes + non-daemon conv turns."""
    import sqlite3
    config = _config()
    daemon = DreamDaemon(config, lattice_db=lattice_db, conv_db=conv_db)
    # 3 lattice nodes since cutoff
    with sqlite3.connect(str(lattice_db)) as con:
        for i in range(3):
            con.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, created_at, updated_at) "
                "VALUES (?, 'memory', 'lattice', 'aetheria', 'x', 0.5, 0.5, "
                "0, ?, ?)",
                (f"n-{i}", f"2026-06-08T01:0{i}:00", f"2026-06-08T01:0{i}:00"),
            )
    # 4 chat turns since cutoff
    _seed_conversation_meta(conv_db, session_id="chat",
                            agent="aetheria", title=None)
    for i in range(4):
        _seed_conversation_turn(conv_db, session_id="chat",
                                agent="aetheria", role="user",
                                content=str(i),
                                ts=f"2026-06-08T02:0{i}:00")
    cutoff = datetime(2026, 6, 8, 0, 0, 0)
    assert daemon._new_input_count_since(cutoff) == 7


def test_new_input_count_unblocks_nothing_to_dream_about_when_only_conv(
    lattice_db, conv_db,
):
    """The 2026-06-08 fix: zero lattice nodes but plenty of conv turns
    should NOT trigger NOTHING_TO_DREAM_ABOUT — the dream gate now
    counts conversations as input. Without this fix, the dream daemon
    skipped two consecutive nights even though Aetheria had hundreds
    of turns per day in conv_store."""
    config = _config()
    daemon = DreamDaemon(config, lattice_db=lattice_db, conv_db=conv_db)
    # Zero lattice writes since the last dream
    # But 10 chat turns since
    _seed_conversation_meta(conv_db, session_id="chat",
                            agent="aetheria", title=None)
    for i in range(10):
        _seed_conversation_turn(conv_db, session_id="chat",
                                agent="aetheria", role="user",
                                content=f"turn {i}",
                                ts=f"2026-06-08T03:{i:02d}:00")
    cutoff = datetime(2026, 6, 8, 0, 0, 0)
    count = daemon._new_input_count_since(cutoff)
    assert count == 10
    # And the gate would let the daemon proceed: count > 0.
