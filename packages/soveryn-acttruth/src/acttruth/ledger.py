"""Append-only episodic truth ledger.

Short summaries + optional evidence refs — not a second Lattice.
Quiet failures (timeouts, tool errors, soft no-ops) are first-class kinds.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Literal

EventKind = Literal[
    "tool_ok",
    "tool_error",
    "timeout",
    "heartbeat",
    "patrol",
    "cutover",
    "note",
    "budget_deny",
    "budget_spend",
]


@dataclass(frozen=True)
class LedgerEvent:
    id: str
    ts: str
    agent_id: str
    kind: EventKind
    summary: str
    ok: bool
    tool: str | None = None
    action: str | None = None
    evidence_ref: str | None = None
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "agent_id": self.agent_id,
            "kind": self.kind,
            "summary": self.summary,
            "ok": self.ok,
            "tool": self.tool,
            "action": self.action,
            "evidence_ref": self.evidence_ref,
            "tags": list(self.tags),
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS acttruth_events (
    id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    ok INTEGER NOT NULL,
    tool TEXT,
    action TEXT,
    evidence_ref TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_acttruth_agent_ts
    ON acttruth_events (agent_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_acttruth_kind_ts
    ON acttruth_events (kind, ts DESC);
"""


class LedgerStore:
    """SQLite append-only ledger. Thread-safe enough for house use (one write/txn)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)
            self._migrate_legacy_tables(con)

    @staticmethod
    def _migrate_legacy_tables(con: sqlite3.Connection) -> None:
        """Rename continuum_* tables from the codename era if present."""
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='continuum_events'"
        ).fetchone()
        new = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='acttruth_events'"
        ).fetchone()
        if row and new:
            # Both exist (fresh schema + old data file): copy missing rows then drop old.
            con.execute(
                "INSERT OR IGNORE INTO acttruth_events "
                "SELECT * FROM continuum_events"
            )
            con.execute("DROP TABLE continuum_events")
            con.commit()
        elif row and not new:
            con.execute("ALTER TABLE continuum_events RENAME TO acttruth_events")
            con.commit()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=30.0)
        con.row_factory = sqlite3.Row
        return con

    def record(
        self,
        *,
        agent_id: str,
        kind: EventKind,
        summary: str,
        ok: bool,
        tool: str | None = None,
        action: str | None = None,
        evidence_ref: str | None = None,
        tags: Iterable[str] | None = None,
        ts: str | None = None,
        event_id: str | None = None,
    ) -> LedgerEvent:
        summary = " ".join((summary or "").split())
        if len(summary) > 500:
            summary = summary[:499].rstrip() + "…"
        if not summary:
            summary = kind
        event = LedgerEvent(
            id=event_id or str(uuid.uuid4()),
            ts=ts or datetime.now().isoformat(timespec="seconds"),
            agent_id=agent_id.strip().lower(),
            kind=kind,
            summary=summary,
            ok=bool(ok),
            tool=tool,
            action=action,
            evidence_ref=evidence_ref,
            tags=tuple(t for t in (tags or ()) if t),
        )
        with self._connect() as con:
            con.execute(
                "INSERT INTO acttruth_events "
                "(id, ts, agent_id, kind, summary, ok, tool, action, evidence_ref, tags_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.ts,
                    event.agent_id,
                    event.kind,
                    event.summary,
                    1 if event.ok else 0,
                    event.tool,
                    event.action,
                    event.evidence_ref,
                    json.dumps(list(event.tags)),
                ),
            )
            con.commit()
        return event

    def recent(
        self,
        agent_id: str,
        *,
        limit: int = 20,
        since: datetime | None = None,
        kinds: Iterable[str] | None = None,
        failures_only: bool = False,
    ) -> list[LedgerEvent]:
        agent = agent_id.strip().lower()
        limit = max(1, min(int(limit), 200))
        clauses = ["agent_id = ?"]
        params: list[Any] = [agent]
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since.isoformat(timespec="seconds"))
        if kinds:
            kind_list = list(kinds)
            placeholders = ",".join("?" * len(kind_list))
            clauses.append(f"kind IN ({placeholders})")
            params.extend(kind_list)
        if failures_only:
            clauses.append("ok = 0")
        sql = (
            "SELECT * FROM acttruth_events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY ts DESC LIMIT ?"
        )
        params.append(limit)
        with self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def since(
        self,
        *,
        since: datetime | None = None,
        limit: int = 5000,
        agent_id: str | None = None,
    ) -> list[LedgerEvent]:
        """Crew-wide (or one agent) events newest-first — for stats/proof."""
        limit = max(1, min(int(limit), 20000))
        clauses: list[str] = []
        params: list[Any] = []
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id.strip().lower())
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since.isoformat(timespec="seconds"))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM acttruth_events{where} ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        with self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def recall_brief(
        self,
        agent_id: str,
        *,
        limit: int = 8,
        window_hours: float = 24.0,
        max_chars: int = 1200,
    ) -> str:
        """Human block for continuity / self-audit. Empty string if nothing."""
        since = datetime.now() - timedelta(hours=window_hours)
        events = self.recent(agent_id, limit=limit, since=since)
        if not events:
            return ""
        lines = ["[ACTTRUTH — what actually happened]"]
        for ev in events:
            mark = "ok" if ev.ok else "FAIL"
            tool = f" {ev.tool}" if ev.tool else ""
            lines.append(f"- ({mark}) {ev.ts} [{ev.kind}]{tool}: {ev.summary}")
        lines.append("[/ACTTRUTH]")
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        return text

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> LedgerEvent:
        try:
            tags = tuple(json.loads(row["tags_json"] or "[]"))
        except (json.JSONDecodeError, TypeError):
            tags = ()
        return LedgerEvent(
            id=row["id"],
            ts=row["ts"],
            agent_id=row["agent_id"],
            kind=row["kind"],  # type: ignore[arg-type]
            summary=row["summary"],
            ok=bool(row["ok"]),
            tool=row["tool"],
            action=row["action"],
            evidence_ref=row["evidence_ref"],
            tags=tags,
        )


@dataclass
class ActTruth:
    """Facade: ledger + budget behind one handle."""

    ledger: LedgerStore
    budget: Any = None  # BudgetStore; typed loosely to avoid cycle at import
    root: Path = field(default_factory=Path)

    @classmethod
    def open(cls, root: Path) -> ActTruth:
        from acttruth.budget import BudgetStore

        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        return cls(
            ledger=LedgerStore(root / "ledger.db"),
            budget=BudgetStore(root / "budget.db"),
            root=root,
        )
