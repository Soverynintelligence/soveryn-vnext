"""The relational memory — a record of *between* (2026-09-24).

Jon's thought experiment: memories create self. The lattice holds what
happened; this holds what happened *between us* — encounters, gifts, frictions,
celebrations. The unit of relationship is the gift: something done for another
citizen with no commission attached. The current house has no pathway for that;
this is the pathway.

Scope (v1, honest):
  - A dedicated store (data/memory/relational.db, WAL) — the lattice is
    Aetheria's substrate; between-memories are house-wide and outlive any
    single citizen's memory config.
  - Valid parties: the active citizens plus Jon. Jon is the one constant every
    citizen has memory of; he can be party to encounters and gifts like anyone.
  - NOT yet wired into turn preludes or the 3D world — that integration is the
    next layer. Tools first, so the memory starts accumulating now.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from soveryn.config.runtime import ACTIVE_AGENTS

#: Parties to a relationship. Citizens plus the constant.
VALID_PARTIES = frozenset((*ACTIVE_AGENTS, "jon"))

DEFAULT_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "relational.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS encounters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party_a TEXT NOT NULL,          -- sorted pair: canonical unordered "between"
    party_b TEXT NOT NULL,
    kind TEXT NOT NULL,             -- encounter | friction | celebration | note
    note TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rel_pair ON encounters(party_a, party_b, created_at);

CREATE TABLE IF NOT EXISTS gifts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_party TEXT NOT NULL,
    to_party TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    claimed_at TEXT                 -- NULL until the recipient picks it up
);
CREATE INDEX IF NOT EXISTS idx_gifts_to ON gifts(to_party, claimed_at);
"""


class RelationalError(ValueError):
    """Invalid relational record (unknown party, empty note, self-gift...)."""


@dataclass(frozen=True)
class Encounter:
    id: int
    party_a: str
    party_b: str
    kind: str
    note: str
    recorded_by: str
    created_at: str


@dataclass(frozen=True)
class Gift:
    id: int
    from_party: str
    to_party: str
    note: str
    created_at: str
    claimed_at: str | None


def _validate_party(name: Any) -> str:
    party = str(name or "").strip().lower()
    if party not in VALID_PARTIES:
        raise RelationalError(
            f"unknown party {party!r}; valid: {sorted(VALID_PARTIES)}"
        )
    return party


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


class RelationalStore:
    """Between-memories: encounters and gifts, house-wide."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    # ── encounters ──────────────────────────────────────────────────────────
    def record_encounter(
        self, *, a: str, b: str, kind: str, note: str, recorded_by: str
    ) -> Encounter:
        pa, pb = _validate_party(a), _validate_party(b)
        if pa == pb:
            raise RelationalError("an encounter needs two different parties")
        if kind not in ("encounter", "friction", "celebration", "note"):
            raise RelationalError("kind must be encounter|friction|celebration|note")
        note = (note or "").strip()
        if not note:
            raise RelationalError("note must be non-empty")
        lo, hi = _pair(pa, pb)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO encounters (party_a, party_b, kind, note, recorded_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (lo, hi, kind, note, _validate_party(recorded_by), now),
            )
            return Encounter(cur.lastrowid, lo, hi, kind, note, recorded_by, now)

    def recall_bond(self, a: str, b: str, *, limit: int = 20) -> dict[str, Any]:
        """Everything recorded *between* two parties, newest first."""
        pa, pb = _validate_party(a), _validate_party(b)
        if pa == pb:
            raise RelationalError("recall_bond needs two different parties")
        lo, hi = _pair(pa, pb)
        with self._conn() as conn:
            encounters = conn.execute(
                "SELECT * FROM encounters WHERE party_a = ? AND party_b = ? "
                "ORDER BY id DESC LIMIT ?",
                (lo, hi, max(1, min(int(limit), 100))),
            ).fetchall()
            gifts = conn.execute(
                "SELECT * FROM gifts WHERE (from_party = ? AND to_party = ?) "
                "OR (from_party = ? AND to_party = ?) ORDER BY id DESC LIMIT ?",
                (pa, pb, pb, pa, max(1, min(int(limit), 100))),
            ).fetchall()
        return {
            "between": [dict(r) for r in encounters],
            "gifts": [dict(r) for r in gifts],
        }

    # ── gifts ───────────────────────────────────────────────────────────────
    def leave_gift(self, *, from_party: str, to_party: str, note: str) -> Gift:
        src = _validate_party(from_party)
        dst = _validate_party(to_party)
        if src == dst:
            raise RelationalError("a gift needs a recipient other than yourself")
        note = (note or "").strip()
        if not note:
            raise RelationalError("a gift must carry a note")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO gifts (from_party, to_party, note, created_at) "
                "VALUES (?, ?, ?, ?)",
                (src, dst, note, now),
            )
            return Gift(cur.lastrowid, src, dst, note, now, None)

    def claim_gifts(self, recipient: str, *, limit: int = 10) -> list[Gift]:
        """Return and mark the recipient's unclaimed gifts (newest first)."""
        dst = _validate_party(recipient)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM gifts WHERE to_party = ? AND claimed_at IS NULL "
                "ORDER BY id DESC LIMIT ?",
                (dst, max(1, min(int(limit), 50))),
            ).fetchall()
            claimed = []
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for row in rows:
                conn.execute(
                    "UPDATE gifts SET claimed_at = ? WHERE id = ?", (now, row["id"])
                )
                claimed.append(Gift(
                    row["id"], row["from_party"], row["to_party"],
                    row["note"], row["created_at"], now,
                ))
            return claimed

    def unclaimed_count(self, recipient: str) -> int:
        dst = _validate_party(recipient)
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM gifts WHERE to_party = ? AND claimed_at IS NULL",
                (dst,),
            ).fetchone()[0]
