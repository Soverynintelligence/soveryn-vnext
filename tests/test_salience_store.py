"""Tests for soveryn.platform.salience.store. Uses tmp_path — never production.

Covers Task 1 of the Salience Engine plan:
    schema bootstrap, insert validation, retrieval ordering,
    promote/dismiss guards, and 14-day decay.

Marker detection itself ships in Task 2 — these tests only need MarkerHit
as a value type.
"""

from __future__ import annotations
import sqlite3
from datetime import datetime, timedelta

import pytest

from soveryn.platform.salience.markers import MarkerHit
from soveryn.platform.salience.store import (
    CONTENT_HEAD_CHARS,
    DEFAULT_DECAY_DAYS,
    SalienceCandidate,
    SalienceStoreError,
    STATUS_DECAYED,
    STATUS_DISMISSED,
    STATUS_PENDING,
    STATUS_PROMOTED,
    create_buffer_table,
    decay_old_pending,
    insert_candidate,
    mark_dismissed,
    mark_promoted,
    pending_candidates_since,
)


# ─── Schema ─────────────────────────────────────────────────────────────────


def test_create_buffer_table_creates_schema(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    con = sqlite3.connect(str(db))
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(salience_buffer)")}
        assert cols == {
            "id", "session_id", "turn_rowid", "turn_role", "turn_content_head",
            "detected_at", "markers", "heuristic_score", "novelty_score",
            "combined_score", "status", "reviewed_at", "library_node_id",
        }
        idx = {r[1] for r in con.execute("PRAGMA index_list(salience_buffer)")}
        assert any("status_detected" in name for name in idx)
    finally:
        con.close()


def test_create_buffer_table_is_idempotent(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    create_buffer_table(db)  # second call must not raise


def test_create_buffer_table_creates_parent_dir(tmp_path):
    # Production path layout uses data/salience_vnext.db — startup wires
    # data/ which may not exist on a fresh checkout. The helper must
    # mkdir parents=True so callers don't need to pre-create.
    db = tmp_path / "nested" / "subdir" / "salience.db"
    create_buffer_table(db)
    assert db.exists()


# ─── Insert + retrieve ──────────────────────────────────────────────────────


def test_insert_then_retrieve(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    cand_id = insert_candidate(
        db,
        session_id="s1",
        turn_rowid=42,
        turn_role="user",
        turn_content_head="The plan is locked.",
        markers=(hit,),
        heuristic_score=4.0,
        novelty_score=None,
    )
    assert cand_id and isinstance(cand_id, str) and len(cand_id) == 36

    since = datetime.now() - timedelta(hours=1)
    rows = pending_candidates_since(db, since=since)
    assert len(rows) == 1
    c = rows[0]
    assert isinstance(c, SalienceCandidate)
    assert c.session_id == "s1"
    assert c.turn_rowid == 42
    assert c.turn_role == "user"
    assert c.markers == (hit,)
    assert c.status == STATUS_PENDING
    assert c.heuristic_score == 4.0
    # novelty_score=None → combined == heuristic
    assert c.novelty_score is None
    assert c.combined_score == 4.0
    assert c.reviewed_at is None
    assert c.library_node_id is None


def test_insert_candidate_rejects_no_markers_and_no_novelty(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    with pytest.raises(ValueError):
        insert_candidate(
            db,
            session_id="s1",
            turn_rowid=1,
            turn_role="user",
            turn_content_head="...",
            markers=(),
            heuristic_score=0.0,
            novelty_score=None,
        )


def test_insert_candidate_accepts_novelty_only(tmp_path):
    # Empty markers + novelty is the "Phase 2" lane — embedding novelty
    # surfaces a candidate without any heuristic match. Must NOT raise.
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    cand_id = insert_candidate(
        db,
        session_id="s1",
        turn_rowid=7,
        turn_role="assistant",
        turn_content_head="a quiet but unfamiliar thought",
        markers=(),
        heuristic_score=0.0,
        novelty_score=0.3,
    )
    rows = pending_candidates_since(db, since=datetime.now() - timedelta(hours=1))
    assert len(rows) == 1
    # combined = 0 + max(0, 0.3) * 5.0 = 1.5
    assert rows[0].combined_score == pytest.approx(1.5)
    assert rows[0].novelty_score == pytest.approx(0.3)
    assert rows[0].id == cand_id


def test_insert_trims_content_head_to_cap(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    long_text = "x" * (CONTENT_HEAD_CHARS + 50)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    insert_candidate(
        db,
        session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head=long_text, markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    rows = pending_candidates_since(db, since=datetime.now() - timedelta(hours=1))
    assert len(rows[0].turn_content_head) == CONTENT_HEAD_CHARS


def test_pending_orders_by_combined_score_desc(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    pivot = MarkerHit(category="pivot", marker="but", weight=2)
    hard = MarkerHit(category="hard_lock", marker="locked", weight=4)
    low_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="pivoty", markers=(pivot,),
        heuristic_score=2.0, novelty_score=None,
    )
    high_id = insert_candidate(
        db, session_id="s1", turn_rowid=2, turn_role="user",
        turn_content_head="locked", markers=(hard,),
        heuristic_score=4.0, novelty_score=None,
    )
    rows = pending_candidates_since(db, since=datetime.now() - timedelta(hours=1))
    assert [r.id for r in rows] == [high_id, low_id]
    assert rows[0].combined_score > rows[1].combined_score


def test_pending_respects_limit(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    for i in range(5):
        insert_candidate(
            db, session_id="s1", turn_rowid=i, turn_role="user",
            turn_content_head=f"row {i}", markers=(hit,),
            heuristic_score=4.0, novelty_score=None,
        )
    rows = pending_candidates_since(
        db, since=datetime.now() - timedelta(hours=1), limit=2
    )
    assert len(rows) == 2


# ─── State transitions ──────────────────────────────────────────────────────


def test_mark_promoted_flips_status_and_records_library_id(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="synthesis", marker="the realization is", weight=3)
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="assistant",
        turn_content_head="...", markers=(hit,),
        heuristic_score=3.0, novelty_score=None,
    )
    mark_promoted(db, candidate_id=cand_id, library_node_id="lib-node-7")
    rows = pending_candidates_since(db, since=datetime.now() - timedelta(hours=1))
    assert len(rows) == 0  # no longer pending
    # Verify the row itself reflects the new state
    with sqlite3.connect(str(db)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT status, library_node_id, reviewed_at "
            "FROM salience_buffer WHERE id = ?",
            (cand_id,),
        ).fetchone()
    assert row["status"] == STATUS_PROMOTED
    assert row["library_node_id"] == "lib-node-7"
    assert row["reviewed_at"] is not None


def test_mark_promoted_raises_when_already_decided(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="...", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    mark_promoted(db, candidate_id=cand_id, library_node_id="lib-1")
    with pytest.raises(SalienceStoreError, match="already"):
        mark_promoted(db, candidate_id=cand_id, library_node_id="lib-2")


def test_mark_promoted_raises_when_not_found(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    with pytest.raises(SalienceStoreError, match="not found"):
        mark_promoted(db, candidate_id="does-not-exist", library_node_id="lib-x")


def test_mark_dismissed_flips_to_dismissed(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="...", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    mark_dismissed(db, candidate_id=cand_id)
    rows = pending_candidates_since(db, since=datetime.now() - timedelta(hours=1))
    assert len(rows) == 0
    with sqlite3.connect(str(db)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT status, library_node_id, reviewed_at "
            "FROM salience_buffer WHERE id = ?",
            (cand_id,),
        ).fetchone()
    assert row["status"] == STATUS_DISMISSED
    # dismiss never sets a library_node_id
    assert row["library_node_id"] is None
    assert row["reviewed_at"] is not None


def test_mark_dismissed_raises_when_already_decided(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="...", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    mark_promoted(db, candidate_id=cand_id, library_node_id="lib-1")
    with pytest.raises(SalienceStoreError, match="already"):
        mark_dismissed(db, candidate_id=cand_id)


def test_mark_dismissed_raises_when_not_found(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    with pytest.raises(SalienceStoreError, match="not found"):
        mark_dismissed(db, candidate_id="nope")


# ─── Decay ──────────────────────────────────────────────────────────────────


def _backdate(db, cand_id: str, days: int) -> None:
    backdated = (datetime.now() - timedelta(days=days)).isoformat()
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "UPDATE salience_buffer SET detected_at = ? WHERE id = ?",
            (backdated, cand_id),
        )


def test_decay_flips_old_pending_to_decayed(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="ancient", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    _backdate(db, cand_id, days=20)
    decayed = decay_old_pending(db, older_than_days=14)
    assert decayed == 1
    rows = pending_candidates_since(db, since=datetime.now() - timedelta(days=30))
    assert len(rows) == 0  # decayed, not pending
    with sqlite3.connect(str(db)) as con:
        status = con.execute(
            "SELECT status FROM salience_buffer WHERE id = ?", (cand_id,)
        ).fetchone()[0]
    assert status == STATUS_DECAYED


def test_decay_leaves_fresh_pending_untouched(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="fresh", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    decayed = decay_old_pending(db, older_than_days=14)
    assert decayed == 0


def test_decay_default_is_14_days(tmp_path):
    assert DEFAULT_DECAY_DAYS == 14
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="boundary", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    _backdate(db, cand_id, days=15)
    # Call WITHOUT older_than_days to verify the 14-day default fires.
    assert decay_old_pending(db) == 1


def test_decay_does_not_touch_promoted_or_dismissed(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    promoted_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="p", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    dismissed_id = insert_candidate(
        db, session_id="s1", turn_rowid=2, turn_role="user",
        turn_content_head="d", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    mark_promoted(db, candidate_id=promoted_id, library_node_id="lib-1")
    mark_dismissed(db, candidate_id=dismissed_id)
    _backdate(db, promoted_id, days=30)
    _backdate(db, dismissed_id, days=30)
    assert decay_old_pending(db, older_than_days=14) == 0
    with sqlite3.connect(str(db)) as con:
        con.row_factory = sqlite3.Row
        rows = {r["id"]: r["status"] for r in con.execute(
            "SELECT id, status FROM salience_buffer"
        )}
    assert rows[promoted_id] == STATUS_PROMOTED
    assert rows[dismissed_id] == STATUS_DISMISSED
