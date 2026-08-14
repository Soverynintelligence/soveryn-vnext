"""Duties — standing obligations of a citizen (charter §5, project §7).

A duty is not a commission. Commissions are discrete work items that start
queued and end done/failed. Duties are what the house *owes itself* on a
schedule or continuously: chat readiness, heartbeat, patrol, dream.

Phase 3 principle: **register first, rewire later**. Seeding a duty does not
take over the systemd unit; it makes the obligation visible on the board so
Jon can see that heartbeat belongs to Aetheria, patrol to Vett, and so on.

Ids are stable (`aetheria:heartbeat`) so re-seeding is an upsert, never a
duplicate row.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

# Fixed founding roster — matches CITIZENS in census.py and charter §3.
FOUNDING_DUTIES: tuple[tuple[str, str, str, str, str | None], ...] = (
    # id, citizen_id, kind, title, schedule
    ("aetheria:chat", "aetheria", "chat", "Chat", None),
    ("aetheria:chief_of_staff", "aetheria", "chief_of_staff",
     "Chief of Staff — route house post, assign commissions", "continuous"),
    ("aetheria:heartbeat", "aetheria", "heartbeat", "Heartbeat", "interval:1800"),
    ("aetheria:dream", "aetheria", "dream", "Dream", "quiet_hours:23:00-07:00"),
    ("aetheria:signal", "aetheria", "signal", "Signal bridge", "continuous"),
    ("aetheria:commission_worker", "aetheria", "commission_worker",
     "Commission runtime", "continuous"),
    ("vett:chat", "vett", "chat", "Chat", None),
    ("vett:patrol", "vett", "patrol", "Patrol", "interval:patrol"),
    ("vett:commission_worker", "vett", "commission_worker",
     "Commission runtime", "continuous"),
    ("scotty:chat", "scotty", "chat", "Chat", None),
    ("scotty:commission_worker", "scotty", "commission_worker",
     "Commission runtime (desk worker)", "continuous"),
    ("scotty:presence", "scotty", "presence",
     "Desk worker / residence", "continuous"),
)


@dataclass(frozen=True)
class Duty:
    id: str
    citizen_id: str
    kind: str
    title: str = ""
    schedule: str | None = None
    enabled: bool = True


def seed_founding(conn: sqlite3.Connection) -> int:
    """Upsert founding duties. Returns how many rows were written/updated.

    Safe to run on every census. Never deletes a duty Jon disabled — only
    refreshes title/schedule for known ids when re-enabled defaults apply.
    """
    written = 0
    for duty_id, citizen_id, kind, title, schedule in FOUNDING_DUTIES:
        # Citizen must exist (FK). Census registers before seeding.
        exists = conn.execute(
            "SELECT 1 FROM citizens WHERE id = ?", (citizen_id,)
        ).fetchone()
        if exists is None:
            continue
        row = conn.execute(
            "SELECT id, enabled FROM duties WHERE id = ?", (duty_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO duties (id, citizen_id, kind, schedule, enabled, title) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (duty_id, citizen_id, kind, schedule, title),
            )
            written += 1
        else:
            # Refresh declaration fields; leave enabled as Jon set it.
            conn.execute(
                "UPDATE duties SET citizen_id = ?, kind = ?, schedule = ?, title = ? "
                "WHERE id = ?",
                (citizen_id, kind, schedule, title, duty_id),
            )
            written += 1
    conn.commit()
    return written


def for_citizen(
    conn: sqlite3.Connection, citizen_id: str, *, enabled_only: bool = False
) -> list[dict[str, Any]]:
    if enabled_only:
        rows = conn.execute(
            "SELECT * FROM duties WHERE citizen_id = ? AND enabled = 1 "
            "ORDER BY kind ASC, id ASC",
            (citizen_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM duties WHERE citizen_id = ? "
            "ORDER BY kind ASC, id ASC",
            (citizen_id,),
        ).fetchall()
    return [_row(r) for r in rows]


def list_all(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM duties ORDER BY citizen_id ASC, kind ASC, id ASC"
    ).fetchall()
    return [_row(r) for r in rows]


def set_enabled(
    conn: sqlite3.Connection, duty_id: str, *, enabled: bool
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id FROM duties WHERE id = ?", (duty_id,)
    ).fetchone()
    if row is None:
        raise KeyError(duty_id)
    conn.execute(
        "UPDATE duties SET enabled = ? WHERE id = ?",
        (1 if enabled else 0, duty_id),
    )
    conn.commit()
    got = conn.execute(
        "SELECT * FROM duties WHERE id = ?", (duty_id,)
    ).fetchone()
    assert got is not None
    return _row(got)


def _row(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    d["enabled"] = bool(d.get("enabled"))
    # title may be missing on pre-migration rows
    d.setdefault("title", d.get("kind") or "")
    return d
