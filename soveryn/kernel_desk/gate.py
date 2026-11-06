"""Pending-approval store for Desk Kernel dangerous tool calls (revamp phase 1).

SQLite at <data_root>/memory/desk_gate.db (own file; approvals.db untouched).
Statuses: pending -> approved | denied | expired. An approval lets exactly one
call run: the extension reads it once and the row is marked consumed.
Every request and decision stays in the table as the audit log.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

# Per-boot secret the Desk's Pi child presents to /api/desk-gate/check.
GATE_TOKEN = os.environ.get("SOVERYN_DESK_GATE_TOKEN_OVERRIDE") or secrets.token_hex(24)
DEFAULT_TTL_S = 900

_lock = threading.Lock()


def db_path() -> Path:
    raw = os.environ.get("SOVERYN_DESK_GATE_DB", "").strip()
    if raw:
        return Path(raw)
    from soveryn.paths import SoverynPaths
    return SoverynPaths.root() / "data" / "memory" / "desk_gate.db"


def _conn(path: Path | None = None) -> sqlite3.Connection:
    p = path or db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p), timeout=5)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS gate (
        id TEXT PRIMARY KEY, created REAL, decided REAL, status TEXT,
        tool TEXT, args TEXT, cwd TEXT, session TEXT, rule TEXT, reason TEXT,
        consumed INTEGER DEFAULT 0)""")
    return c


def _row(r) -> dict:
    d = dict(r)
    try:
        d["args"] = json.loads(d.get("args") or "{}")
    except ValueError:
        pass
    return d


def create(tool, args, cwd, session, rule, reason, path=None) -> dict:
    gid = "g" + secrets.token_hex(8)
    with _lock, _conn(path) as c:
        c.execute("INSERT INTO gate (id,created,status,tool,args,cwd,session,rule,reason) VALUES (?,?,?,?,?,?,?,?,?)",
                  (gid, time.time(), "pending", tool, json.dumps(args)[:20000], cwd, session, rule, reason))
    return get(gid, path)


def _expire(c, ttl=DEFAULT_TTL_S):
    c.execute("UPDATE gate SET status='expired', decided=? WHERE status='pending' AND created < ?",
              (time.time(), time.time() - ttl))


def get(gid, path=None) -> dict | None:
    with _lock, _conn(path) as c:
        _expire(c)
        r = c.execute("SELECT * FROM gate WHERE id=?", (gid,)).fetchone()
    return _row(r) if r else None


def decide(gid, decision, path=None) -> dict | None:
    if decision not in ("approved", "denied"):
        raise ValueError("decision must be approved|denied")
    with _lock, _conn(path) as c:
        _expire(c)
        cur = c.execute("UPDATE gate SET status=?, decided=? WHERE id=? AND status='pending'",
                        (decision, time.time(), gid))
        changed = cur.rowcount
    row = get(gid, path)
    return row if changed else None


def consume(gid, path=None) -> dict | None:
    """Mark an approved row used; returns the row (status at time of read)."""
    with _lock, _conn(path) as c:
        _expire(c)
        r = c.execute("SELECT * FROM gate WHERE id=?", (gid,)).fetchone()
        if r and r["status"] == "approved" and not r["consumed"]:
            c.execute("UPDATE gate SET consumed=1 WHERE id=?", (gid,))
            d = _row(r); d["consumed"] = 0
            return d
    return _row(r) if r else None


def list_recent(limit=50, path=None) -> list[dict]:
    with _lock, _conn(path) as c:
        _expire(c)
        rows = c.execute("SELECT * FROM gate ORDER BY created DESC LIMIT ?", (int(limit),)).fetchall()
    return [_row(r) for r in rows]
