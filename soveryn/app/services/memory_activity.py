"""Lattice write activity — daily counts and totals for the command center.

Reads directly from LatticeStore's underlying sqlite connection. The query
groups by date(created_at) for the last N days. Per-agent breakdown is
included so the activity feed can color-code.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from soveryn.memory.lattice import LatticeStore


@dataclass(frozen=True)
class DailyBucket:
    date: str                 # ISO date, e.g. "2026-05-24"
    count: int
    by_agent: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryActivity:
    days: int
    buckets: list[DailyBucket]  # oldest-first


def daily_write_counts(store: LatticeStore, *, days: int = 14, now: datetime | None = None) -> MemoryActivity:
    now = now or datetime.now(timezone.utc)
    today = now.date()
    earliest = today - timedelta(days=days - 1)

    with store._conn() as conn:
        rows = conn.execute(
            "SELECT date(created_at) AS d, agent, COUNT(*) AS n "
            "FROM nodes "
            "WHERE date(created_at) >= ? "
            "GROUP BY date(created_at), agent",
            (earliest.isoformat(),),
        ).fetchall()

    by_date: dict[str, dict[str, int]] = {}
    for row in rows:
        d = row["d"]
        by_date.setdefault(d, {})[row["agent"]] = row["n"]

    buckets: list[DailyBucket] = []
    for offset in range(days):
        d = (earliest + timedelta(days=offset)).isoformat()
        per_agent = by_date.get(d, {})
        buckets.append(DailyBucket(date=d, count=sum(per_agent.values()), by_agent=per_agent))
    return MemoryActivity(days=days, buckets=buckets)


def total_node_count(store: LatticeStore) -> int:
    with store._conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()
        return int(row["n"]) if row else 0
