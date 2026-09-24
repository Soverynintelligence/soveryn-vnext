"""Extras for commissions: get, cancel, state filter, is_running."""
from __future__ import annotations

import pytest

from soveryn.citizens.commissions import (
    cancel,
    claim,
    enqueue,
    for_citizen,
    get,
    is_running,
)
from soveryn.citizens.registry import Citizen, connect, register


@pytest.fixture()
def db(tmp_path):
    with connect(tmp_path / "citizens.db") as conn:
        register(conn, Citizen(id="vett", display_name="V.E.T.T."))
        yield conn


def test_get_returns_row_or_none(db):
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    assert get(db, cid)["body"] == "task"
    assert get(db, "nope") is None


def test_cancel_queued_marks_failed(db):
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    row = cancel(db, cid, at="2026-08-14T09:05:00Z", reason="never mind")
    assert row["state"] == "failed"
    assert "never mind" in row["error"]


def test_cancel_running_refused(db):
    cid = enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    claim(db, "vett", worker="w", at="2026-08-14T09:01:00Z")
    with pytest.raises(ValueError):
        cancel(db, cid, at="2026-08-14T09:05:00Z")


def test_for_citizen_state_filter(db):
    a = enqueue(db, "vett", "a", at="2026-08-14T09:00:00Z")
    b = enqueue(db, "vett", "b", at="2026-08-14T09:01:00Z")
    # claim takes oldest first → a running, b still queued
    claimed = claim(db, "vett", worker="w", at="2026-08-14T09:02:00Z")
    assert claimed["id"] == a
    queued = for_citizen(db, "vett", state="queued")
    assert len(queued) == 1
    assert queued[0]["id"] == b
    assert queued[0]["body"] == "b"
    assert all(r["state"] == "queued" for r in queued)


def test_is_running(db):
    assert is_running(db, "vett") is False
    enqueue(db, "vett", "task", at="2026-08-14T09:00:00Z")
    claim(db, "vett", worker="w", at="2026-08-14T09:01:00Z")
    assert is_running(db, "vett") is True


def test_begin_owned_is_running_and_not_claimable(db):
    from soveryn.citizens.commissions import begin_owned, claim, get

    cid = begin_owned(
        db, "vett", "heartbeat pulse", worker="heartbeat",
        at="2026-08-14T09:00:00Z",
    )
    row = get(db, cid)
    assert row["state"] == "running"
    assert row["claimed_by"] == "heartbeat"
    assert claim(db, "vett", worker="citizens-runtime",
                 at="2026-08-14T09:00:01Z") is None
