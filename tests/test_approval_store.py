"""Unit tests for ApprovalStore / ApprovalBroker."""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.platform.approval.store import (
    STATE_APPROVED,
    STATE_DENIED,
    STATE_EXPIRED,
    STATE_PENDING,
    ApprovalBroker,
    ApprovalStore,
)


@pytest.fixture
def store(tmp_path: Path) -> ApprovalStore:
    return ApprovalStore(tmp_path / "approvals.db")


def test_pending_for_and_pending_all(store: ApprovalStore) -> None:
    a = store.create(
        citizen="aetheria", tool="email_send", args={"to": "x@y.z"}, now="2026-08-20T10:00:00"
    )
    b = store.create(
        citizen="eve", tool="messenger_send", args={"text": "hi"}, now="2026-08-20T10:01:00"
    )
    store.set_state(a.id, state=STATE_APPROVED, now="2026-08-20T10:02:00", decided_by="jon")

    assert [r.id for r in store.pending_for("eve")] == [b.id]
    assert store.pending_for("aetheria") == []
    assert [r.id for r in store.pending_all()] == [b.id]
    assert store.pending_all()[0].tool == "messenger_send"


def test_broker_decide_approve_and_deny(store: ApprovalStore) -> None:
    broker = ApprovalBroker(store, ttl_seconds=30.0, poll_interval_seconds=0.01)
    req = broker.request(
        citizen="vett", tool="web_search", args={"q": "x"}, now="2026-08-20T11:00:00"
    )
    assert req.state == STATE_PENDING

    approved = broker.decide(req.id, approve=True, decided_by="jon", now="2026-08-20T11:00:01")
    assert approved is not None
    assert approved.state == STATE_APPROVED
    assert approved.decided_by == "jon"

    req2 = broker.request(
        citizen="vett", tool="email_send", args={"to": "a@b.c"}, now="2026-08-20T11:00:02"
    )
    denied = broker.decide(req2.id, approve=False, decided_by="jon", now="2026-08-20T11:00:03")
    assert denied is not None
    assert denied.state == STATE_DENIED


def test_expire_stale(store: ApprovalStore) -> None:
    old = store.create(
        citizen="kernel", tool="email_send", args={}, now="2026-08-20T09:00:00"
    )
    fresh = store.create(
        citizen="kernel", tool="messenger_send", args={}, now="2026-08-20T10:00:00"
    )
    expired = store.expire_stale("2026-08-20T10:00:10", ttl_seconds=60.0)
    assert [r.id for r in expired] == [old.id]
    assert store.get(old.id).state == STATE_EXPIRED
    assert store.get(fresh.id).state == STATE_PENDING
    assert [r.id for r in store.pending_all()] == [fresh.id]
