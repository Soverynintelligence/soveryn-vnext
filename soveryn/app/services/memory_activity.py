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


@dataclass(frozen=True)
class LibraryWrite:
    id: str
    agent: str
    content_head: str  # first ~140 chars, single-line
    created_at: str
    tags: tuple[str, ...]


# Library layer holds curated synthesis writes (type='library') and the older
# document-chunk bootstrap (type='library_chunk'). The feed surfaces only
# 'library' — those are the deliberate writes Aetheria + agents make as part
# of their work, not document-chunking infrastructure.
_LIBRARY_FEED_NODE_TYPE = "library"


def recent_library_writes(
    store: LatticeStore,
    *,
    limit: int = 12,
    agent_filter: str | None = None,
    tag_contains: str | None = None,
) -> list[LibraryWrite]:
    """Return the most recent library-layer writes (newest first).

    Filters to type='library' to surface deliberate synthesis writes, not
    document-chunk fragments from the initial library bootstrap.

    agent_filter: when given, restrict to writes by that agent name.
    tag_contains: when given, restrict to writes whose tags contain a
                  string match for this needle (case-insensitive substring).
    """
    limit = max(1, min(limit, 100))
    sql = (
        "SELECT id, agent, content, created_at, tags FROM nodes "
        "WHERE layer = 'library' AND type = ?"
    )
    params: list = [_LIBRARY_FEED_NODE_TYPE]
    if agent_filter is not None and agent_filter.strip():
        sql += " AND agent = ?"
        params.append(agent_filter.strip())
    if tag_contains is not None and tag_contains.strip():
        # tags is a JSON array string; LIKE on the raw column with case
        # insensitivity for friendly UI matching. The Python filter below
        # double-checks on the parsed tags so we don't accept incidental
        # content matches.
        sql += " AND LOWER(tags) LIKE ?"
        params.append(f"%{tag_contains.strip().lower()}%")
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with store._conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out: list[LibraryWrite] = []
    for row in rows:
        # Single-line head — collapse newlines so the feed row stays compact.
        raw = (row["content"] or "").replace("\r", "").replace("\n", " ").strip()
        head = raw[:140]
        if len(raw) > 140:
            head = head.rstrip() + "…"
        # tags is JSON-encoded list[str]; tolerate missing / malformed.
        import json
        try:
            tags = tuple(json.loads(row["tags"] or "[]"))
        except (ValueError, TypeError):
            tags = ()
        # Tag-filter double-check: the SQL LIKE matched the raw JSON
        # string; verify the needle is actually in one of the parsed
        # tags (case-insensitive) so we don't accept matches that hit
        # only the JSON syntax characters.
        if tag_contains is not None and tag_contains.strip():
            needle = tag_contains.strip().lower()
            if not any(needle in t.lower() for t in tags if isinstance(t, str)):
                continue
        out.append(LibraryWrite(
            id=row["id"],
            agent=row["agent"] or "unknown",
            content_head=head,
            created_at=row["created_at"],
            tags=tags,
        ))
    return out
