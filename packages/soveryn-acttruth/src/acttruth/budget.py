"""Unprompted competence budget.

Quiet is success: deny returns a stand-down reason for the heartbeat brief.
Counts *actions* (tool-using unprompted work), not notes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_WINDOW_SECONDS = 6 * 3600
DEFAULT_MAX_ACTIONS = 2


@dataclass(frozen=True)
class BudgetPolicy:
    window_seconds: int = DEFAULT_WINDOW_SECONDS
    max_unprompted_actions: int = DEFAULT_MAX_ACTIONS


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    remaining: int
    used: int
    limit: int
    reason: str = ""

    @property
    def stand_down_note(self) -> str:
        if self.allowed:
            return ""
        return (
            "ACTTRUTH BUDGET EXHAUSTED: you have used your unprompted action "
            f"allowance ({self.used}/{self.limit} in the current window). "
            "Leave a short note if useful. Do NOT call tools. Quiet is correct."
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS acttruth_budget_spends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_acttruth_budget_agent_ts
    ON acttruth_budget_spends (agent_id, ts DESC);
"""


class BudgetStore:
    def __init__(
        self,
        db_path: Path,
        *,
        policy: BudgetPolicy | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy or BudgetPolicy()
        with self._connect() as con:
            con.executescript(_SCHEMA)
            self._migrate_legacy_tables(con)

    @staticmethod
    def _migrate_legacy_tables(con: sqlite3.Connection) -> None:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='continuum_budget_spends'"
        ).fetchone()
        new = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='acttruth_budget_spends'"
        ).fetchone()
        if row and new:
            con.execute(
                "INSERT OR IGNORE INTO acttruth_budget_spends "
                "SELECT * FROM continuum_budget_spends"
            )
            con.execute("DROP TABLE continuum_budget_spends")
            con.commit()
        elif row and not new:
            con.execute(
                "ALTER TABLE continuum_budget_spends RENAME TO acttruth_budget_spends"
            )
            con.commit()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=30.0)
        con.row_factory = sqlite3.Row
        return con

    def _window_start(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now()
        return now - timedelta(seconds=self.policy.window_seconds)

    def used(self, agent_id: str, *, now: datetime | None = None) -> int:
        agent = agent_id.strip().lower()
        since = self._window_start(now).isoformat(timespec="seconds")
        with self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) AS n FROM acttruth_budget_spends "
                "WHERE agent_id = ? AND ts >= ?",
                (agent, since),
            ).fetchone()
        return int(row["n"] if row else 0)

    def check(self, agent_id: str, *, now: datetime | None = None) -> BudgetDecision:
        used = self.used(agent_id, now=now)
        limit = self.policy.max_unprompted_actions
        remaining = max(0, limit - used)
        if remaining > 0:
            return BudgetDecision(
                allowed=True,
                remaining=remaining,
                used=used,
                limit=limit,
            )
        return BudgetDecision(
            allowed=False,
            remaining=0,
            used=used,
            limit=limit,
            reason=f"unprompted budget exhausted ({used}/{limit})",
        )

    def spend(
        self,
        agent_id: str,
        *,
        kind: str = "heartbeat_action",
        summary: str = "",
        now: datetime | None = None,
    ) -> BudgetDecision:
        """Record a spend if still allowed. Idempotent check-then-insert."""
        decision = self.check(agent_id, now=now)
        if not decision.allowed:
            return decision
        ts = (now or datetime.now()).isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute(
                "INSERT INTO acttruth_budget_spends (ts, agent_id, kind, summary) "
                "VALUES (?, ?, ?, ?)",
                (ts, agent_id.strip().lower(), kind, (summary or "")[:300]),
            )
            con.commit()
        return self.check(agent_id, now=now)
