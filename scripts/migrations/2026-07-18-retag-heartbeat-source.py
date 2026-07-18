"""One-time surgical re-tag of historical heartbeat pulse turns.

Historical `[HEARTBEAT]` pulse turns (and their assistant reflections) were
written with `source='direct'` before source-threading (Task 1) existed.
This migration re-tags them to `source='heartbeat'` — but ONLY within
sessions titled `[heartbeat] aetheria`, and ONLY the actual pulse turns.

Some sessions titled `[heartbeat] aetheria` also contain a handful of real
human <-> Aetheria conversations that were interjected into that session
(e.g. Jon checking in mid-heartbeat). Those real turns, and the assistant
turns answering them, MUST stay `source='direct'`. So this cannot be a
blanket UPDATE keyed on session title alone — it has to look at each row.

Pairing rule (see retag_heartbeat_turns docstring for the precise
definition): a row qualifies for retagging iff:
  - it is a `user` turn whose content starts with `[HEARTBEAT]`, OR
  - it is an `assistant` turn whose most-recent PRECEDING turn in the same
    session (by rowid order) that is a `user` turn itself qualifies (i.e.
    starts with `[HEARTBEAT]`).

Only rows currently `source='direct'` are touched, so re-running this
script is a no-op the second time.

Usage (after review — this mutates the live DB, so it is NOT run
automatically on import):

    /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python \\
        scripts/migrations/2026-07-18-retag-heartbeat-source.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

HEARTBEAT_SESSION_TITLE = "[heartbeat] aetheria"
HEARTBEAT_PREFIX = "[HEARTBEAT]"

LIVE_DB_PATH = Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"
BACKUP_SUFFIX = ".backup-2026-07-18"


def backup_db(live_path: str | Path, backup_path: str | Path) -> None:
    """Full, WAL-consistent snapshot of a live sqlite DB via the online backup API.

    A plain file copy of a WAL-mode database can silently omit rows that are
    committed but not yet checkpointed into the main .db file (they live in
    the -wal sidecar). The sqlite online backup API (Connection.backup) reads
    through the live connection and captures all committed data regardless of
    checkpoint state, producing a faithful snapshot safe to use as a rollback
    point.

    Refuses to overwrite an existing backup.
    """
    backup_path = Path(backup_path)
    if backup_path.exists():
        raise SystemExit(f"backup already exists, refusing to overwrite: {backup_path}")
    src = sqlite3.connect(str(live_path))
    try:
        dst = sqlite3.connect(str(backup_path))
        try:
            with dst:
                src.backup(dst)  # captures WAL-resident committed data
        finally:
            dst.close()
    finally:
        src.close()


def retag_heartbeat_turns(conn: sqlite3.Connection) -> dict:
    """Re-tag historical heartbeat pulse turns from 'direct' to 'heartbeat'.

    Scope is limited to sessions whose conversation_meta.title equals
    '[heartbeat] aetheria'. Within those sessions only, a row is retagged
    iff it is a user turn starting with '[HEARTBEAT]', or an assistant turn
    whose most-recent preceding user turn (by rowid order, within the same
    session) starts with '[HEARTBEAT]'. Only rows currently
    source='direct' are ever changed — idempotent by construction.

    Returns {"retagged": int, "left_direct": int} where left_direct counts
    rows IN SCOPE (i.e. in a qualifying session) whose source is 'direct'
    after this call — the real human turns deliberately preserved.
    Rows outside scope (other sessions) are never touched or counted.
    """
    session_ids = [
        row[0]
        for row in conn.execute(
            "SELECT session_id FROM conversation_meta WHERE title = ?",
            (HEARTBEAT_SESSION_TITLE,),
        ).fetchall()
    ]

    retag_ids: list[int] = []
    left_direct = 0

    for session_id in session_ids:
        rows = conn.execute(
            "SELECT rowid, role, content, source FROM conversations "
            "WHERE session_id = ? ORDER BY rowid",
            (session_id,),
        ).fetchall()

        preceding_user_is_heartbeat = False
        for rowid, role, content, source in rows:
            if role == "user":
                is_heartbeat = (content or "").startswith(HEARTBEAT_PREFIX)
                preceding_user_is_heartbeat = is_heartbeat
            elif role == "assistant":
                is_heartbeat = preceding_user_is_heartbeat
            else:
                is_heartbeat = False

            if is_heartbeat:
                if source == "direct":
                    retag_ids.append(rowid)
            else:
                if source == "direct":
                    left_direct += 1
                # else: already retagged in a prior run — not in scope of
                # "left_direct" (which tracks preserved-direct rows), and
                # not re-counted as retagged either.

    if retag_ids:
        conn.executemany(
            "UPDATE conversations SET source = 'heartbeat' WHERE rowid = ?",
            [(rowid,) for rowid in retag_ids],
        )

    return {"retagged": len(retag_ids), "left_direct": left_direct}


def _source_counts(conn: sqlite3.Connection) -> dict:
    return dict(conn.execute("SELECT source, COUNT(*) FROM conversations GROUP BY source").fetchall())


def main() -> None:
    if not LIVE_DB_PATH.exists():
        raise SystemExit(f"Live DB not found at {LIVE_DB_PATH}")

    backup_path = LIVE_DB_PATH.with_name(LIVE_DB_PATH.name + BACKUP_SUFFIX)
    backup_db(LIVE_DB_PATH, backup_path)
    print(f"Backed up {LIVE_DB_PATH} -> {backup_path}")

    conn = sqlite3.connect(LIVE_DB_PATH)
    try:
        before = _source_counts(conn)
        print(f"BEFORE per-source counts: {before}")

        result = retag_heartbeat_turns(conn)
        conn.commit()

        after = _source_counts(conn)
        print(f"AFTER per-source counts:  {after}")
        print(f"Result: {result}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
