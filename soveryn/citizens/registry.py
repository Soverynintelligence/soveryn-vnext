"""SOVERYN Citizens — the registry (charter §9.1).

Path-injected SQLite, per the house rule: no module-level connection, the
caller decides where the file lives, tests pass tmp_path.

The one design decision worth defending
---------------------------------------
`status` is **derived from evidence, never stored as a declaration**. The
charter makes status visible (§1.5) and accountability a duty (§5), and neither
means anything if a row can simply claim `resident`. So this module splits what
it is *told* from what it has *seen*:

  register()  records the declaration — name, soul, model server, workspace.
              These are Jon's grants (§6) and are safe to assert.
  observe()   records evidence — a real check, at a real time, that either
              found the citizen's process or did not.
  status_of() derives the answer from the latest observation. Nothing else can
              set it.

There is no code path that writes "resident". A citizen becomes resident by
being observed, and stops being resident by being observed absent.

Why `unobserved` exists
-----------------------
The charter's vocabulary is `resident | on_duty | blocked | offline | retired`,
which has no way to say "we have not looked". That gap is not academic:

  * Scotty has no unit and no endpoint — he is invoked on demand. Reporting him
    `offline` would assert a failed process; there is no process to fail.
  * Aetheria runs on the tower with no public endpoint, so a public surface
    cannot probe her either. The Lab page hit exactly this and had to grow a
    hollow dot for it.

`offline` is a claim about a thing that was looked for and not found.
`unobserved` is the honest state before that. Adding it needs a charter
amendment under §12 — flagged, not smuggled.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0

# What an observation can conclude. Deliberately only two: a probe either found
# the process or it did not. Anything richer is interpretation, and belongs to
# the caller that ran the probe.
OBSERVED_PRESENT = "present"
OBSERVED_ABSENT = "absent"

STATUS_UNOBSERVED = "unobserved"
STATUS_RESIDENT = "resident"
STATUS_OFFLINE = "offline"
STATUS_RETIRED = "retired"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS citizens (
  id             TEXT PRIMARY KEY,
  display_name   TEXT NOT NULL,
  soul_path      TEXT,
  model_server   TEXT,
  workspace_path TEXT,
  last_seen_at   TEXT,
  retired_at     TEXT,
  notes          TEXT
);

-- Evidence, append-only. The citizens row holds no status column on purpose:
-- there is nowhere to write one.
CREATE TABLE IF NOT EXISTS observations (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  citizen_id TEXT NOT NULL REFERENCES citizens(id) ON DELETE CASCADE,
  finding    TEXT NOT NULL CHECK (finding IN ('present','absent')),
  observed_at TEXT NOT NULL,
  detail     TEXT
);
CREATE INDEX IF NOT EXISTS observations_by_citizen
  ON observations(citizen_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS duties (
  id         TEXT PRIMARY KEY,
  citizen_id TEXT NOT NULL REFERENCES citizens(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL,
  schedule   TEXT,
  enabled    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS commissions (
  id           TEXT PRIMARY KEY,
  citizen_id   TEXT NOT NULL REFERENCES citizens(id) ON DELETE CASCADE,
  body         TEXT NOT NULL,
  state        TEXT NOT NULL DEFAULT 'queued'
               CHECK (state IN ('queued','running','done','failed')),
  result_ref   TEXT,
  created_at   TEXT,
  completed_at TEXT
);
CREATE INDEX IF NOT EXISTS commissions_by_citizen
  ON commissions(citizen_id, created_at DESC);
"""


@dataclass
class Citizen:
    """A declaration: what Jon granted. Never a claim about liveness."""

    id: str
    display_name: str
    soul_path: str = ""
    model_server: str = ""
    workspace_path: str = ""
    notes: str = ""


@contextmanager
def connect(path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(path), timeout=DEFAULT_CONNECTION_TIMEOUT_SECONDS)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA)
        conn.commit()
        yield conn
    finally:
        conn.close()


def register(conn: sqlite3.Connection, citizen: Citizen) -> None:
    """Record or update a declaration. Evidence is untouched.

    Re-registering is how a desk move or a soul path change is recorded; it must
    not reset `last_seen_at`, because that would let a rewrite of the
    declaration quietly erase the observation history behind it.
    """
    conn.execute(
        """
        INSERT INTO citizens (id, display_name, soul_path, model_server,
                              workspace_path, notes)
        VALUES (:id, :display_name, :soul_path, :model_server,
                :workspace_path, :notes)
        ON CONFLICT(id) DO UPDATE SET
          display_name   = excluded.display_name,
          soul_path      = excluded.soul_path,
          model_server   = excluded.model_server,
          workspace_path = excluded.workspace_path,
          notes          = excluded.notes
        """,
        {
            "id": citizen.id,
            "display_name": citizen.display_name,
            "soul_path": citizen.soul_path,
            "model_server": citizen.model_server,
            "workspace_path": citizen.workspace_path,
            "notes": citizen.notes,
        },
    )
    conn.commit()


def observe(
    conn: sqlite3.Connection,
    citizen_id: str,
    finding: str,
    *,
    at: str,
    detail: str = "",
) -> None:
    """Record that someone actually looked, and what they found."""
    if finding not in (OBSERVED_PRESENT, OBSERVED_ABSENT):
        raise ValueError(f"finding must be present/absent, got {finding!r}")
    exists = conn.execute(
        "SELECT 1 FROM citizens WHERE id = ?", (citizen_id,)
    ).fetchone()
    if not exists:
        raise KeyError(f"no citizen {citizen_id!r} — register before observing")

    conn.execute(
        "INSERT INTO observations (citizen_id, finding, observed_at, detail) "
        "VALUES (?, ?, ?, ?)",
        (citizen_id, finding, at, detail),
    )
    # last_seen_at means "last seen ALIVE", not "last polled", so an absent
    # finding must not advance it.
    if finding == OBSERVED_PRESENT:
        conn.execute(
            "UPDATE citizens SET last_seen_at = ? WHERE id = ?", (at, citizen_id)
        )
    conn.commit()


def retire(conn: sqlite3.Connection, citizen_id: str, *, at: str = "") -> None:
    """Jon revoking standing (§6). Outranks any observation."""
    conn.execute(
        "UPDATE citizens SET retired_at = ? WHERE id = ?",
        (at or "retired", citizen_id),
    )
    conn.commit()


def status_of(conn: sqlite3.Connection, citizen_id: str) -> str:
    row = conn.execute(
        "SELECT retired_at FROM citizens WHERE id = ?", (citizen_id,)
    ).fetchone()
    if row is None:
        raise KeyError(citizen_id)
    if row["retired_at"]:
        return STATUS_RETIRED

    latest = conn.execute(
        "SELECT finding FROM observations WHERE citizen_id = ? "
        "ORDER BY observed_at DESC, id DESC LIMIT 1",
        (citizen_id,),
    ).fetchone()
    if latest is None:
        return STATUS_UNOBSERVED
    return STATUS_RESIDENT if latest["finding"] == OBSERVED_PRESENT else STATUS_OFFLINE


def list_citizens(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every citizen with its derived status — the shape `/api/citizens` serves."""
    out: list[dict[str, Any]] = []
    for row in conn.execute("SELECT * FROM citizens ORDER BY id").fetchall():
        record = dict(row)
        record["status"] = status_of(conn, row["id"])
        last = conn.execute(
            "SELECT finding, observed_at, detail FROM observations "
            "WHERE citizen_id = ? ORDER BY observed_at DESC, id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        record["last_observation"] = dict(last) if last else None
        out.append(record)
    return out
