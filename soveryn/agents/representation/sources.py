"""Read-only all-agent evidence snapshot; IDs match novelty_gate's full history."""
from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from soveryn.agents.representation.novelty_gate import to_ny

log = logging.getLogger(__name__)
RECENT_DAYS = 7
AUTONOMOUS_PREFIXES = (
    "⚙️", "🤖", "[daemon]", "[ares]", "[signal]", "[heartbeat]",
    "[patrol]", "[webhook]", "[commission]", "automation:",
)


def is_autonomous_title(title: str | None, source: str | None = None) -> bool:
    if (source or "").casefold() in {
        "automation", "teammates_overnight", "heartbeat", "daemon", "patrol", "webhook", "commission",
    }:
        return True
    return bool(title and title.lstrip().casefold().startswith(
        tuple(p.casefold() for p in AUTONOMOUS_PREFIXES)))


@dataclass(frozen=True)
class EvidenceTurn:
    id: str
    agent: str
    role: str
    content: str
    timestamp: datetime
    session_id: str
    title: str | None
    session_agent: str | None = None


def recent_turns(conv_store, *, now: datetime, source_agent: str | None = None) -> list[EvidenceTurn]:
    """One snapshot across EVERY stored agent, never only the output owner.

    Enumerate every role in rowid order BEFORE filtering to retain the exact
    turn:<session UUID>:<full-history index> resolved by the novelty gate.
    No metadata activity cutoff: stale metadata must not hide a recent turn.
    Unknown users remain unknown; source agent is not a human identity.
    """
    hi = to_ny(now)
    lo = hi - timedelta(days=RECENT_DAYS)
    con = sqlite3.connect(f"file:{conv_store.db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT c.session_id,c.agent,c.role,c.content,c.timestamp,m.title,c.source,m.agent "
            "FROM conversations c LEFT JOIN conversation_meta m "
            "ON m.session_id=c.session_id ORDER BY c.rowid ASC"
        ).fetchall()
    finally:
        con.close()
    indices: dict[str, int] = defaultdict(int)
    out = []
    for sid, agent, role, content, stamp, title, source, session_agent in rows:
        idx = indices[sid]
        indices[sid] += 1
        if source_agent is not None and (
            (session_agent or agent) != source_agent or agent != source_agent
        ):
            continue
        if is_autonomous_title(title, source) or role not in ("user", "assistant"):
            continue
        if len((content or "").strip()) < 20:
            continue
        try:
            ts = to_ny(stamp)
        except (ValueError, TypeError):
            log.warning("representation invalid turn timestamp: session=%s index=%d", sid, idx)
            continue
        if lo <= ts <= hi:
            out.append(EvidenceTurn(f"turn:{sid}:{idx}", agent, role,
                                    content, ts, sid, title, session_agent))
    return sorted(out, key=lambda t: (t.timestamp, t.id))
