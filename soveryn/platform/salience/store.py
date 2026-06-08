"""Salience buffer SQLite store.

Separate DB file from lattice/conv — young, evolving table, kept out of
critical recall WAL. Path-injected per Jon constraint 2: no module-level
DB connection; caller decides DB location (production wiring picks
salience_vnext.db; tests pass tmp_path).

Public surface (matches soveryn/platform/salience/__init__.py exports):
    - SalienceCandidate            (frozen dataclass)
    - SalienceStoreError           (Exception)
    - create_buffer_table          (idempotent schema bootstrap)
    - insert_candidate             (returns new uuid)
    - pending_candidates_since     (ordered by combined_score DESC)
    - mark_promoted / mark_dismissed
    - decay_old_pending            (status pending → decayed past cutoff)
    - status constants: STATUS_PENDING / _PROMOTED / _DISMISSED / _DECAYED

Combined-score formula (locked in design doc):
    combined = heuristic + (max(0, novelty) * 5.0 if novelty is not None else 0)
The 5.0 multiplier keeps a 0.30 cosine distance worth 1.5 — a clear nudge
over a Pivot (weight 2) but below a Hard Lock (weight 4) — so heuristic
markers stay the primary ranker until novelty proves itself.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from soveryn.platform.salience.markers import MarkerHit


STATUS_PENDING = "pending"
STATUS_PROMOTED = "promoted"
STATUS_DISMISSED = "dismissed"
STATUS_DECAYED = "decayed"

DEFAULT_DECAY_DAYS = 14
CONTENT_HEAD_CHARS = 200


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS salience_buffer (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_rowid INTEGER NOT NULL,
    turn_role TEXT NOT NULL,
    turn_content_head TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    markers TEXT NOT NULL,
    heuristic_score REAL NOT NULL DEFAULT 0,
    novelty_score REAL,
    combined_score REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewed_at TEXT,
    library_node_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_salience_status_detected
    ON salience_buffer(status, detected_at);

CREATE INDEX IF NOT EXISTS idx_salience_session
    ON salience_buffer(session_id);
"""


class SalienceStoreError(Exception):
    """Raised on validation / state errors in the salience buffer."""


@dataclass(frozen=True)
class SalienceCandidate:
    id: str
    session_id: str
    turn_rowid: int
    turn_role: str
    turn_content_head: str
    detected_at: str
    markers: tuple[MarkerHit, ...]
    heuristic_score: float
    novelty_score: float | None
    combined_score: float
    status: str
    reviewed_at: str | None
    library_node_id: str | None


# ─── Schema bootstrap ────────────────────────────────────────────────────────


def create_buffer_table(db_path: Path | str) -> None:
    """Idempotently create the salience_buffer table + indices.

    Creates the parent directory if needed (mirrors ConversationStore
    behavior — production wiring relies on this so app startup can hand
    in a path under data/ that may not exist yet on a fresh checkout).
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as con:
        con.executescript(_SCHEMA_SQL)


# ─── Insert ──────────────────────────────────────────────────────────────────


def _combined_score(heuristic_score: float, novelty_score: float | None) -> float:
    if novelty_score is None:
        return float(heuristic_score)
    return float(heuristic_score) + max(0.0, float(novelty_score)) * 5.0


def insert_candidate(
    db_path: Path | str,
    *,
    session_id: str,
    turn_rowid: int,
    turn_role: str,
    turn_content_head: str,
    markers: Sequence[MarkerHit],
    heuristic_score: float,
    novelty_score: float | None,
) -> str:
    """Insert a pending candidate; return its new uuid.

    Raises ValueError if both markers is empty and novelty_score is None —
    the buffer is for *flagged* turns; if neither lane fired there's
    nothing to flag.
    """
    if not markers and novelty_score is None:
        raise ValueError(
            "insert_candidate requires at least one marker OR a novelty score"
        )
    cand_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    combined = _combined_score(heuristic_score, novelty_score)
    markers_json = json.dumps(
        [{"category": m.category, "marker": m.marker, "weight": m.weight} for m in markers]
    )
    head = (turn_content_head or "")[:CONTENT_HEAD_CHARS]
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO salience_buffer "
            "(id, session_id, turn_rowid, turn_role, turn_content_head, "
            " detected_at, markers, heuristic_score, novelty_score, "
            " combined_score, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cand_id, session_id, turn_rowid, turn_role, head, now,
                markers_json, float(heuristic_score), novelty_score,
                combined, STATUS_PENDING,
            ),
        )
    return cand_id


# ─── Read ────────────────────────────────────────────────────────────────────


def _row_to_candidate(row: sqlite3.Row) -> SalienceCandidate:
    raw = json.loads(row["markers"] or "[]")
    markers = tuple(
        MarkerHit(category=m["category"], marker=m["marker"], weight=m["weight"])
        for m in raw
    )
    return SalienceCandidate(
        id=row["id"],
        session_id=row["session_id"],
        turn_rowid=row["turn_rowid"],
        turn_role=row["turn_role"],
        turn_content_head=row["turn_content_head"],
        detected_at=row["detected_at"],
        markers=markers,
        heuristic_score=row["heuristic_score"],
        novelty_score=row["novelty_score"],
        combined_score=row["combined_score"],
        status=row["status"],
        reviewed_at=row["reviewed_at"],
        library_node_id=row["library_node_id"],
    )


def pending_candidates_since(
    db_path: Path | str,
    *,
    since: datetime,
    limit: int = 50,
) -> list[SalienceCandidate]:
    """Return pending candidates flagged at or after `since`.

    Ordering: combined_score DESC, then detected_at DESC. The heartbeat
    digest renderer (Task 4) walks this in order and stops at its display
    cap, so the highest-impact candidates surface first.
    """
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, session_id, turn_rowid, turn_role, turn_content_head, "
            "       detected_at, markers, heuristic_score, novelty_score, "
            "       combined_score, status, reviewed_at, library_node_id "
            "FROM salience_buffer "
            "WHERE status = ? AND detected_at >= ? "
            "ORDER BY combined_score DESC, detected_at DESC "
            "LIMIT ?",
            (STATUS_PENDING, since.isoformat(), limit),
        ).fetchall()
    return [_row_to_candidate(r) for r in rows]


# ─── State transitions ──────────────────────────────────────────────────────


def mark_promoted(
    db_path: Path | str,
    *,
    candidate_id: str,
    library_node_id: str,
) -> None:
    """Flip pending → promoted, record the resulting library node id.

    Raises SalienceStoreError if the candidate doesn't exist or is no
    longer pending — guards against double-promote when the heartbeat
    fires twice with the same digest.
    """
    now = datetime.now().isoformat()
    with sqlite3.connect(str(db_path)) as con:
        row = con.execute(
            "SELECT status FROM salience_buffer WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise SalienceStoreError(f"candidate {candidate_id!r} not found")
        if row[0] != STATUS_PENDING:
            raise SalienceStoreError(
                f"candidate {candidate_id!r} already {row[0]} — cannot re-promote"
            )
        con.execute(
            "UPDATE salience_buffer "
            "SET status = ?, reviewed_at = ?, library_node_id = ? "
            "WHERE id = ?",
            (STATUS_PROMOTED, now, library_node_id, candidate_id),
        )


def mark_dismissed(db_path: Path | str, *, candidate_id: str) -> None:
    """Flip pending → dismissed. Same not-found / already-decided guards as promote."""
    now = datetime.now().isoformat()
    with sqlite3.connect(str(db_path)) as con:
        row = con.execute(
            "SELECT status FROM salience_buffer WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise SalienceStoreError(f"candidate {candidate_id!r} not found")
        if row[0] != STATUS_PENDING:
            raise SalienceStoreError(
                f"candidate {candidate_id!r} already {row[0]}"
            )
        con.execute(
            "UPDATE salience_buffer SET status = ?, reviewed_at = ? WHERE id = ?",
            (STATUS_DISMISSED, now, candidate_id),
        )


# ─── Decay ──────────────────────────────────────────────────────────────────


def decay_old_pending(
    db_path: Path | str,
    *,
    older_than_days: int = DEFAULT_DECAY_DAYS,
) -> int:
    """Flip pending → decayed for any candidate older than the cutoff.

    Returns the count of rows updated. Called from the heartbeat tick
    (Task 6) — bounded so an idle SOVERYN doesn't accumulate stale
    candidates indefinitely.
    """
    cutoff = (datetime.now() - timedelta(days=older_than_days)).isoformat()
    now = datetime.now().isoformat()
    with sqlite3.connect(str(db_path)) as con:
        cur = con.execute(
            "UPDATE salience_buffer SET status = ?, reviewed_at = ? "
            "WHERE status = ? AND detected_at < ?",
            (STATUS_DECAYED, now, STATUS_PENDING, cutoff),
        )
        return cur.rowcount
