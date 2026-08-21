"""Active-now strip: who is mid-work right now (thin, existing signals).

Composes running commissions (heartbeat pulse + discrete work) with
``interactive_busy`` (recent direct/messenger/signal/voice user turns).
No new busy daemon — Command Center polls ``GET /api/active-now``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from soveryn.citizens.commissions import RUNNING
from soveryn.citizens.runtime import interactive_busy

# Cap chips so a stuck queue cannot flood the Easy front door.
_MAX_ACTIVE = 8

_HEARTBEAT_BODY = "heartbeat pulse"


def _is_heartbeat(row: dict[str, Any]) -> bool:
    body = (row.get("body") or "").strip().lower()
    claimed = (row.get("claimed_by") or "").strip().lower()
    return body == _HEARTBEAT_BODY or claimed == "heartbeat" or claimed.startswith(
        "heartbeat"
    )


def _display_names(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT id, display_name FROM citizens").fetchall()
    out: dict[str, str] = {}
    for row in rows:
        cid = row["id"] if isinstance(row, sqlite3.Row) else row[0]
        name = row["display_name"] if isinstance(row, sqlite3.Row) else row[1]
        out[str(cid)] = str(name or cid)
    return out


def _running_commissions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT * FROM commissions WHERE state = ? "
            "ORDER BY COALESCE(claimed_at, created_at) ASC, id ASC",
            (RUNNING,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


def build_active_now(
    citizens_db: str | Path | None,
    conv_db: str | Path | None,
    *,
    within_seconds: int = 90,
    max_items: int = _MAX_ACTIVE,
) -> dict[str, Any]:
    """Return ``{active: [...], count: N}`` for the Active-now strip.

    Best-effort: missing or locked DBs yield an empty list with a note, never raise.
    """
    active: list[dict[str, Any]] = []
    notes: list[str] = []

    names: dict[str, str] = {}
    if citizens_db is not None:
        path = Path(citizens_db)
        if path.exists():
            try:
                with sqlite3.connect(str(path), timeout=5.0) as conn:
                    conn.row_factory = sqlite3.Row
                    names = _display_names(conn)
                    for row in _running_commissions(conn):
                        cid = str(row.get("citizen_id") or "")
                        if not cid:
                            continue
                        kind = "heartbeat" if _is_heartbeat(row) else "commission"
                        display = names.get(cid, cid)
                        active.append(
                            {
                                "citizen": cid,
                                "kind": kind,
                                "label": f"{display} · {kind}",
                                "since": row.get("claimed_at") or row.get("created_at"),
                                "commission_id": row.get("id"),
                            }
                        )
            except sqlite3.Error as exc:
                notes.append(f"citizens db: {exc}")
        else:
            notes.append("no citizens registry")
    else:
        notes.append("citizens db unset")

    # Interactive chat proxy — separate chips even if a commission is also running.
    citizen_ids = list(names.keys()) if names else []
    if not citizen_ids and citizens_db is not None and Path(citizens_db).exists():
        # names empty but db existed — still try founding cast from list
        try:
            with sqlite3.connect(str(citizens_db), timeout=5.0) as conn:
                conn.row_factory = sqlite3.Row
                names = _display_names(conn)
                citizen_ids = list(names.keys())
        except sqlite3.Error:
            pass

    for cid in citizen_ids:
        try:
            if interactive_busy(conv_db, cid, within_seconds=within_seconds):
                display = names.get(cid, cid)
                active.append(
                    {
                        "citizen": cid,
                        "kind": "chat",
                        "label": f"{display} · chat",
                        "since": None,
                        "commission_id": None,
                    }
                )
        except Exception as exc:  # noqa: BLE001 — strip must stay best-effort
            notes.append(f"chat busy {cid}: {exc}")

    # Stable order: commissions (already oldest-first) then chat; cap.
    active = active[:max_items]
    out: dict[str, Any] = {"active": active, "count": len(active)}
    if notes:
        out["note"] = "; ".join(notes)
    return out
