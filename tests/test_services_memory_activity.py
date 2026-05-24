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
