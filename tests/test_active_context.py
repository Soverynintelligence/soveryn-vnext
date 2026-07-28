"""Tests for soveryn.context.active_context and soveryn.context.store."""

import os
import tempfile

import pytest

from soveryn.context.active_context import ActiveContext
from soveryn.context.store import ActiveContextStore


# ── ActiveContext dataclass ──────────────────────────────────────────


def test_active_context_fields():
    ctx = ActiveContext(
        topic="budget",
        summary="Q3 spend review",
        rail="signal",
        updated_at="2026-01-01T00:00:00Z",
        turn_count=5,
    )
    assert ctx.topic == "budget"
    assert ctx.summary == "Q3 spend review"
    assert ctx.rail == "signal"
    assert ctx.updated_at == "2026-01-01T00:00:00Z"
    assert ctx.turn_count == 5


def test_to_dict():
    ctx = ActiveContext(
        topic="x",
        summary="y",
        rail="web",
        updated_at="2026-02-02T12:00:00Z",
        turn_count=1,
    )
    d = ctx.to_dict()
    assert d == {
        "topic": "x",
        "summary": "y",
        "rail": "web",
        "updated_at": "2026-02-02T12:00:00Z",
        "turn_count": 1,
    }


def test_from_dict():
    data = {
        "topic": "deploy",
        "summary": "rolling restart",
        "rail": "messenger",
        "updated_at": "2026-03-03T08:00:00Z",
        "turn_count": 3,
    }
    ctx = ActiveContext.from_dict(data)
    assert ctx.topic == "deploy"
    assert ctx.summary == "rolling restart"
    assert ctx.rail == "messenger"
    assert ctx.updated_at == "2026-03-03T08:00:00Z"
    assert ctx.turn_count == 3


def test_roundtrip():
    original = ActiveContext(
        topic="roundtrip",
        summary="test",
        rail="signal",
        updated_at="2026-01-01T00:00:00Z",
        turn_count=10,
    )
    restored = ActiveContext.from_dict(original.to_dict())
    assert restored == original


# ── ActiveContextStore ───────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test_context.db")
    return ActiveContextStore(db_path)


def test_put_and_get(store):
    ctx = ActiveContext(
        topic="alpha",
        summary="first",
        rail="signal",
        updated_at="2026-01-01T00:00:00Z",
        turn_count=1,
    )
    store.put(ctx)
    result = store.get("alpha")
    assert result is not None
    assert result == ctx


def test_get_missing(store):
    assert store.get("no_such_topic") is None


def test_put_upserts(store):
    ctx1 = ActiveContext(
        topic="beta",
        summary="v1",
        rail="signal",
        updated_at="2026-01-01T00:00:00Z",
        turn_count=1,
    )
    store.put(ctx1)
    ctx2 = ActiveContext(
        topic="beta",
        summary="v2",
        rail="web",
        updated_at="2026-01-02T00:00:00Z",
        turn_count=2,
    )
    store.put(ctx2)
    result = store.get("beta")
    assert result is not None
    assert result == ctx2


def test_latest_empty(store):
    assert store.latest() is None


def test_latest_one(store):
    store.put(
        ActiveContext(
            topic="only",
            summary="just one",
            rail="signal",
            updated_at="2026-01-01T00:00:00Z",
            turn_count=1,
        )
    )
    result = store.latest()
    assert result is not None
    assert result.topic == "only"


def test_latest_most_recent(store):
    store.put(
        ActiveContext(
            topic="old",
            summary="old",
            rail="signal",
            updated_at="2026-01-01T00:00:00Z",
            turn_count=1,
        )
    )
    store.put(
        ActiveContext(
            topic="new",
            summary="new",
            rail="web",
            updated_at="2026-01-02T00:00:00Z",
            turn_count=1,
        )
    )
    result = store.latest()
    assert result is not None
    assert result.topic == "new"


def test_list_all_empty(store):
    assert store.list_all() == []


def test_list_all_newest_first(store):
    store.put(
        ActiveContext(
            topic="first",
            summary="s1",
            rail="signal",
            updated_at="2026-01-01T00:00:00Z",
            turn_count=1,
        )
    )
    store.put(
        ActiveContext(
            topic="second",
            summary="s2",
            rail="web",
            updated_at="2026-01-02T00:00:00Z",
            turn_count=1,
        )
    )
    store.put(
        ActiveContext(
            topic="third",
            summary="s3",
            rail="messenger",
            updated_at="2026-01-03T00:00:00Z",
            turn_count=1,
        )
    )
    results = store.list_all()
    assert len(results) == 3
    assert results[0].topic == "third"
    assert results[1].topic == "second"
    assert results[2].topic == "first"


def test_list_all_after_upsert(store):
    store.put(
        ActiveContext(
            topic="x",
            summary="v1",
            rail="signal",
            updated_at="2026-01-01T00:00:00Z",
            turn_count=1,
        )
    )
    store.put(
        ActiveContext(
            topic="y",
            summary="y",
            rail="web",
            updated_at="2026-01-02T00:00:00Z",
            turn_count=1,
        )
    )
    # Upsert x with a newer timestamp
    store.put(
        ActiveContext(
            topic="x",
            summary="v2",
            rail="web",
            updated_at="2026-01-03T00:00:00Z",
            turn_count=2,
        )
    )
    results = store.list_all()
    assert len(results) == 2
    assert results[0].topic == "x"
    assert results[0].summary == "v2"
    assert results[1].topic == "y"


def test_store_persists_across_instances(tmp_path):
    db_path = str(tmp_path / "persist.db")
    s1 = ActiveContextStore(db_path)
    s1.put(
        ActiveContext(
            topic="persist",
            summary="data",
            rail="signal",
            updated_at="2026-01-01T00:00:00Z",
            turn_count=1,
        )
    )
    s2 = ActiveContextStore(db_path)
    result = s2.get("persist")
    assert result is not None
    assert result.summary == "data"
