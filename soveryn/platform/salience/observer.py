"""Inline salience observer — called after every ConversationStore.save_turn."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from soveryn.platform.salience.markers import detect_markers
from soveryn.platform.salience.store import insert_candidate


logger = logging.getLogger(__name__)


# Daemon-authored sessions whose titles start with these prefixes are NOT
# scored — their outputs would otherwise feed back into the engine that
# triggered them (heartbeat digest → save_turn → flag → next heartbeat).
DAEMON_SESSION_TITLE_PREFIXES: tuple[str, ...] = (
    "[heartbeat]",
    "[signal]",
    "[patrol]",
    "[webhook]",
    "[dream]",
    "[presence]",
)


class SalienceObserver:
    """Wraps marker detection + buffer insertion. Non-fatal by contract."""

    def __init__(self, *, salience_db: Path, conv_db: Path | None = None) -> None:
        self.salience_db = Path(salience_db)
        self.conv_db = Path(conv_db) if conv_db is not None else None

    def on_turn_saved(
        self,
        *,
        session_id: str,
        turn_rowid: int,
        role: str,
        content: str,
    ) -> None:
        try:
            if self.conv_db is not None and self._is_daemon_session(session_id):
                return
            hits = detect_markers(content, role=role)
            if hits == ():
                # Phase 2: novelty scoring lands here — when embeddings find
                # a high-distance turn even without markers, we'll still flag.
                return
            heuristic_score = sum(h.weight for h in hits)
            insert_candidate(
                self.salience_db,
                session_id=session_id,
                turn_rowid=turn_rowid,
                turn_role=role,
                turn_content_head=content,
                markers=hits,
                heuristic_score=float(heuristic_score),
                novelty_score=None,
            )
        except Exception:
            logger.exception(
                "SalienceObserver.on_turn_saved failed (session=%s rowid=%s role=%s)",
                session_id, turn_rowid, role,
            )

    def _is_daemon_session(self, session_id: str) -> bool:
        with sqlite3.connect(str(self.conv_db)) as con:
            row = con.execute(
                "SELECT title FROM conversation_meta WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return False
        title = row[0]
        if not title:
            return False
        return any(title.startswith(p) for p in DAEMON_SESSION_TITLE_PREFIXES)
