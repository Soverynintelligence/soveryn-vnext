"""Service layer for mission control's specialist visibility — listing
active specialists, killing them by id, surfacing recent DAC traffic.

Reads conv_meta directly and joins lattice edges + direct_message nodes
for the comm-bus feed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_ACTIVE_TITLE_PREFIX = "[specialist:"
_KILLED_TITLE_PREFIX = "[specialist-killed:"


@dataclass(frozen=True)
class ActiveSpecialist:
    specialist_id: str
    host_agent: str
    name: str
    coord_node_id: str
    title: str
    created_at: str
    updated_at: str
    age_minutes: int


def _parse_title(title: str) -> tuple[str, str]:
    """Extract (name, coord_node_id) from `[specialist:<name>:<coord_id>]`.
    Returns ("unknown", "unknown") on parse failure."""
    if not title or not title.startswith(_ACTIVE_TITLE_PREFIX):
        return ("unknown", "unknown")
    body = title[len(_ACTIVE_TITLE_PREFIX):].rstrip("]")
    parts = body.split(":", 1)
    if len(parts) != 2:
        return ("unknown", "unknown")
    return parts[0], parts[1]


def list_active_specialists(
    conv_db_path: Path,
    *,
    now: datetime | None = None,
) -> list[ActiveSpecialist]:
    """List all currently-active specialist sessions, newest first."""
    now = now or datetime.now()
    with sqlite3.connect(str(conv_db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT session_id, agent, title, created_at, updated_at "
            "FROM conversation_meta WHERE title LIKE ? "
            "ORDER BY created_at DESC",
            (_ACTIVE_TITLE_PREFIX + "%",),
        ).fetchall()

    out: list[ActiveSpecialist] = []
    for row in rows:
        name, coord = _parse_title(row["title"])
        try:
            created = datetime.fromisoformat(row["created_at"])
            age_minutes = max(0, int((now - created).total_seconds() // 60))
        except (ValueError, TypeError):
            age_minutes = 0
        out.append(ActiveSpecialist(
            specialist_id=row["session_id"],
            host_agent=row["agent"],
            name=name,
            coord_node_id=coord,
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            age_minutes=age_minutes,
        ))
    return out


def kill_specialist(
    conv_db_path: Path,
    *,
    specialist_id: str,
) -> dict:
    """Jon's override — kill an active specialist by retitling to
    '[specialist-killed:...]'. Distinct from Aetheria's terminate_specialist
    (which uses '[specialist-archived:...]') so logs can tell who closed
    a specialist down."""
    with sqlite3.connect(str(conv_db_path)) as con:
        row = con.execute(
            "SELECT title FROM conversation_meta WHERE session_id = ?",
            (specialist_id,),
        ).fetchone()
        if row is None:
            return {"error": "unknown_specialist", "specialist_id": specialist_id}
        title = row[0]
        if not title or not title.startswith(_ACTIVE_TITLE_PREFIX):
            return {
                "error": "not_active_specialist",
                "specialist_id": specialist_id,
                "current_title": title,
            }
        killed_title = _KILLED_TITLE_PREFIX + title[len(_ACTIVE_TITLE_PREFIX):]
        con.execute(
            "UPDATE conversation_meta SET title = ? WHERE session_id = ?",
            (killed_title, specialist_id),
        )
    return {
        "specialist_id": specialist_id,
        "killed_title": killed_title,
    }


@dataclass(frozen=True)
class DacEdge:
    edge_id: str
    relationship: str        # "direct_command" or "direct_query"
    sender: str
    target: str
    coord_node_id: str
    session_id: str
    message_head: str
    created_at: str
    age_minutes: int


def recent_dac_edges(
    lattice_db_path: Path,
    *,
    limit: int = 12,
    now: datetime | None = None,
) -> list[DacEdge]:
    """Recent DAC traffic — join edges with the direct_message source node
    to surface sender/target/coord/message_head per edge."""
    now = now or datetime.now()
    limit = max(1, min(limit, 100))
    with sqlite3.connect(str(lattice_db_path)) as con:
        con.row_factory = sqlite3.Row
        # The edge points: message_node → coord_node.
        # The message_node's provenance carries sender/target/session_id/coord.
        rows = con.execute(
            "SELECT e.id AS edge_id, e.relationship, e.source_id, "
            "e.target_id, e.created_at AS edge_created_at, "
            "n.content AS msg_content, n.provenance AS msg_provenance "
            "FROM edges e "
            "JOIN nodes n ON n.id = e.source_id "
            "WHERE e.relationship IN ('direct_command', 'direct_query') "
            "  AND e.archived = 0 "
            "ORDER BY e.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    import json
    out: list[DacEdge] = []
    for row in rows:
        try:
            prov = json.loads(row["msg_provenance"] or "{}")
        except (ValueError, TypeError):
            prov = {}
        sender = prov.get("sender") or "unknown"
        target = prov.get("target") or "unknown"
        coord = prov.get("coord_node_id") or row["target_id"] or "unknown"
        session_id = prov.get("session_id") or ""
        # Message head: the helper writes content as a multi-line block
        # starting with "[direct_<mode>] sender -> target / session / coord /
        # head:". Surface just the head: line if we can find it.
        content = row["msg_content"] or ""
        head = ""
        for line in content.splitlines():
            if line.startswith("head:"):
                head = line[len("head:"):].strip()
                break
        if not head:
            # Fall back to first non-meta line
            for line in content.splitlines():
                if line and not line.startswith(("[direct_", "session:",
                                                  "coord:", "head:")):
                    head = line.strip()
                    break
        try:
            created = datetime.fromisoformat(row["edge_created_at"])
            age_minutes = max(0, int((now - created).total_seconds() // 60))
        except (ValueError, TypeError):
            age_minutes = 0
        out.append(DacEdge(
            edge_id=row["edge_id"],
            relationship=row["relationship"],
            sender=sender,
            target=target,
            coord_node_id=coord,
            session_id=session_id,
            message_head=head[:160],
            created_at=row["edge_created_at"],
            age_minutes=age_minutes,
        ))
    return out
