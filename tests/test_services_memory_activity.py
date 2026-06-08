"""Tests for soveryn/app/services/memory_activity.py."""

import uuid
from datetime import datetime, timezone, timedelta

import pytest

from soveryn.app.services.memory_activity import (
    daily_write_counts, total_node_count, MemoryActivity,
)
from soveryn.memory.lattice import LatticeStore


@pytest.fixture
def store(tmp_path):
    return LatticeStore(tmp_path / "lattice.db")


def _seed(store, when: datetime, agent: str = "aetheria"):
    # write_node sets created_at internally; we patch via raw SQL to backdate.
    # uuid suffix keeps ids unique when seeding multiple rows at the same (when, agent).
    with store._conn() as conn:
        node_id = f"n-{when.isoformat()}-{agent}-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, access_count, tags, created_at, updated_at)"
            " VALUES (?, 'fact', 'private', ?, 'x', 0.3, 0.5, 0, '[]', ?, ?)",
            (node_id, agent, when.isoformat(), when.isoformat()),
        )


def test_daily_write_counts_empty(store):
    r = daily_write_counts(store, days=7, now=datetime(2026, 5, 24, tzinfo=timezone.utc))
    assert len(r.buckets) == 7
    assert all(b.count == 0 for b in r.buckets)


def test_daily_write_counts_one_per_day(store):
    base = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
    for d in range(7):
        _seed(store, base - timedelta(days=d))
    r = daily_write_counts(store, days=7, now=base)
    counts = sorted(b.count for b in r.buckets)
    assert counts == [1] * 7


def test_daily_write_counts_groups_same_day(store):
    base = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)
    for h in (1, 3, 5, 7):
        _seed(store, base.replace(hour=h))
    r = daily_write_counts(store, days=3, now=base)
    today = [b for b in r.buckets if b.date == base.date().isoformat()]
    assert len(today) == 1
    assert today[0].count == 4


def test_daily_write_counts_excludes_older(store):
    base = datetime(2026, 5, 24, tzinfo=timezone.utc)
    _seed(store, base - timedelta(days=30))  # outside window
    _seed(store, base - timedelta(days=1))   # inside
    r = daily_write_counts(store, days=7, now=base)
    total = sum(b.count for b in r.buckets)
    assert total == 1


def test_daily_write_counts_per_agent(store):
    base = datetime(2026, 5, 24, 12, tzinfo=timezone.utc)
    _seed(store, base, agent="aetheria")
    _seed(store, base, agent="aetheria")
    _seed(store, base, agent="vett")
    r = daily_write_counts(store, days=2, now=base)
    today = [b for b in r.buckets if b.date == base.date().isoformat()][0]
    assert today.by_agent == {"aetheria": 2, "vett": 1}


def test_total_node_count(store):
    base = datetime(2026, 5, 24, 12, tzinfo=timezone.utc)
    _seed(store, base)
    _seed(store, base)
    _seed(store, base)
    assert total_node_count(store) == 3


# ─── recent_library_writes ──────────────────────────────────────────────────


def _seed_library(
    store, when: datetime, *, agent: str = "aetheria",
    node_type: str = "library", content: str = "library note",
    tags: list | None = None,
):
    """Seed a library-layer node with backdated created_at."""
    import json
    with store._conn() as conn:
        node_id = f"lib-{when.isoformat()}-{agent}-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, "
            "salience, access_count, tags, created_at, updated_at) "
            "VALUES (?, ?, 'library', ?, ?, 0.3, 0.5, 0, ?, ?, ?)",
            (node_id, node_type, agent, content, json.dumps(tags or []),
             when.isoformat(), when.isoformat()),
        )
    return node_id


def test_recent_library_writes_returns_only_library_type(store):
    """type='library' surfaces; type='library_chunk' is filtered out as
    document-bootstrap infrastructure, not a meaningful 'write'."""
    from soveryn.app.services.memory_activity import recent_library_writes
    base = datetime(2026, 6, 5, 12, tzinfo=timezone.utc)
    _seed_library(store, base, content="curated milestone note")
    _seed_library(store, base + timedelta(seconds=1),
                  node_type="library_chunk", content="document fragment")
    writes = recent_library_writes(store)
    assert len(writes) == 1
    assert writes[0].content_head == "curated milestone note"


def test_recent_library_writes_newest_first(store):
    from soveryn.app.services.memory_activity import recent_library_writes
    base = datetime(2026, 6, 5, 12, tzinfo=timezone.utc)
    _seed_library(store, base, content="old write")
    _seed_library(store, base + timedelta(minutes=5), content="middle write")
    _seed_library(store, base + timedelta(minutes=10), content="newest write")
    writes = recent_library_writes(store)
    assert [w.content_head for w in writes] == [
        "newest write", "middle write", "old write",
    ]


def test_recent_library_writes_truncates_content_head_with_ellipsis(store):
    from soveryn.app.services.memory_activity import recent_library_writes
    long_content = "x" * 300
    _seed_library(store, datetime(2026, 6, 5, 12, tzinfo=timezone.utc),
                  content=long_content)
    writes = recent_library_writes(store)
    assert len(writes) == 1
    assert writes[0].content_head.endswith("…")
    assert len(writes[0].content_head) <= 141  # 140 + ellipsis


def test_recent_library_writes_collapses_newlines_in_head(store):
    from soveryn.app.services.memory_activity import recent_library_writes
    multiline = "First line of synthesis.\n\nSecond paragraph follows."
    _seed_library(store, datetime(2026, 6, 5, 12, tzinfo=timezone.utc),
                  content=multiline)
    writes = recent_library_writes(store)
    assert "\n" not in writes[0].content_head
    assert "First line of synthesis." in writes[0].content_head


def test_recent_library_writes_respects_limit(store):
    from soveryn.app.services.memory_activity import recent_library_writes
    base = datetime(2026, 6, 5, 12, tzinfo=timezone.utc)
    for i in range(20):
        _seed_library(store, base + timedelta(minutes=i), content=f"w-{i}")
    writes = recent_library_writes(store, limit=5)
    assert len(writes) == 5
    # Newest 5
    assert writes[0].content_head == "w-19"


def test_recent_library_writes_clamps_limit(store):
    """limit below 1 → 1; limit above max → max."""
    from soveryn.app.services.memory_activity import recent_library_writes
    base = datetime(2026, 6, 5, 12, tzinfo=timezone.utc)
    for i in range(5):
        _seed_library(store, base + timedelta(minutes=i), content=f"w-{i}")
    # Negative clamped to 1
    assert len(recent_library_writes(store, limit=-3)) == 1
    # Above max clamped to 100 (we only have 5; just verify no crash)
    assert len(recent_library_writes(store, limit=10000)) == 5


def test_recent_library_writes_empty_lattice(store):
    from soveryn.app.services.memory_activity import recent_library_writes
    assert recent_library_writes(store) == []


def test_recent_library_writes_preserves_per_node_agent_and_tags(store):
    from soveryn.app.services.memory_activity import recent_library_writes
    base = datetime(2026, 6, 5, 12, tzinfo=timezone.utc)
    _seed_library(store, base, agent="scotty",
                  content="DAC milestone", tags=["milestone", "dac"])
    writes = recent_library_writes(store)
    assert writes[0].agent == "scotty"
    assert set(writes[0].tags) == {"milestone", "dac"}
