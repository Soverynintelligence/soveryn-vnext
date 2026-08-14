"""Commission runtime: claim → process → outbox → done (Phase 2 exit)."""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.citizens import commissions
from soveryn.citizens.registry import Citizen, connect, observe, register
from soveryn.citizens.runtime import drain_once, write_outbox


@pytest.fixture()
def house(tmp_path):
    db = tmp_path / "citizens.db"
    desks = tmp_path / "desks"
    with connect(db) as conn:
        register(
            conn,
            Citizen(
                id="aetheria",
                display_name="Aetheria",
                workspace_path=str(desks / "aetheria"),
            ),
        )
        observe(conn, "aetheria", "present", at="2026-08-14T08:00:00Z")
    return db, desks


def test_drain_writes_outbox_and_marks_done(house):
    db, desks = house
    with connect(db) as conn:
        cid = commissions.enqueue(
            conn, "aetheria", "summarize the dock notes into outbox",
            at="2026-08-14T09:00:00Z",
        )

    def process(citizen_id, body, commission_id):
        assert citizen_id == "aetheria"
        assert "dock notes" in body
        assert commission_id == cid
        return "Dock notes: all clear."

    closed = drain_once(
        db, process_fn=process, worker="test", at="2026-08-14T09:01:00Z"
    )
    assert len(closed) == 1
    row = closed[0]
    assert row["state"] == "done"
    assert row["id"] == cid
    out = Path(row["result_ref"])
    assert out.is_file()
    assert out.parent.name == "outbox"
    text = out.read_text(encoding="utf-8")
    assert "Dock notes: all clear." in text
    assert "summarize the dock notes" in text


def test_process_failure_marks_failed_not_done(house):
    db, _ = house
    with connect(db) as conn:
        cid = commissions.enqueue(
            conn, "aetheria", "explode", at="2026-08-14T09:00:00Z"
        )

    def process(citizen_id, body, commission_id):
        raise RuntimeError("model timed out")

    closed = drain_once(
        db, process_fn=process, worker="test", at="2026-08-14T09:01:00Z"
    )
    assert closed[0]["id"] == cid
    assert closed[0]["state"] == "failed"
    assert "model timed out" in (closed[0]["error"] or "")


def test_does_not_claim_second_while_one_running(house):
    db, _ = house
    with connect(db) as conn:
        first = commissions.enqueue(
            conn, "aetheria", "first", at="2026-08-14T09:00:00Z"
        )
        commissions.enqueue(
            conn, "aetheria", "second", at="2026-08-14T09:00:01Z"
        )
        commissions.claim(
            conn, "aetheria", worker="other", at="2026-08-14T09:01:00Z"
        )

    calls = []

    def process(citizen_id, body, commission_id):
        calls.append(body)
        return "ok"

    closed = drain_once(
        db, process_fn=process, worker="test", at="2026-08-14T09:02:00Z"
    )
    assert closed == []
    assert calls == []
    with connect(db) as conn:
        rows = {r["id"]: r for r in commissions.for_citizen(conn, "aetheria")}
        assert rows[first]["state"] == "running"
        # second still queued — not stolen while first runs
        assert any(r["state"] == "queued" for r in rows.values())


def test_write_outbox_creates_drawers(tmp_path):
    path = write_outbox(
        tmp_path / "aetheria",
        "abc-123",
        body="do the thing",
        content="done",
        citizen_id="aetheria",
    )
    assert path.is_file()
    assert "do the thing" in path.read_text()
    assert "done" in path.read_text()


def test_drain_skips_when_busy_fn_says_interactive(house):
    db, _ = house
    with connect(db) as conn:
        commissions.enqueue(
            conn, "aetheria", "summarize the dock", at="2026-08-14T09:00:00Z"
        )

    closed = drain_once(
        db,
        process_fn=lambda *a: "should not run",
        worker="test",
        at="2026-08-14T09:01:00Z",
        busy_fn=lambda cid: cid == "aetheria",
    )
    assert closed == []
    with connect(db) as conn:
        (row,) = commissions.for_citizen(conn, "aetheria")
        assert row["state"] == "queued"


def test_drain_still_takes_work_when_busy_fn_says_idle(house):
    db, _ = house
    with connect(db) as conn:
        commissions.enqueue(
            conn, "aetheria", "summarize the dock", at="2026-08-14T09:00:00Z"
        )

    closed = drain_once(
        db,
        process_fn=lambda *a: "ok",
        worker="test",
        at="2026-08-14T09:01:00Z",
        busy_fn=lambda cid: False,
    )
    assert len(closed) == 1
    assert closed[0]["state"] == "done"


def test_interactive_busy_detects_recent_direct_user_turn(tmp_path):
    from soveryn.citizens.runtime import interactive_busy
    from soveryn.memory.conversation_store import ConversationStore

    conv = ConversationStore(tmp_path / "conv.db")
    sid = conv.new_session("aetheria", title="chat")
    conv.save_turn(sid, "aetheria", "user", "hi", source="direct")
    assert interactive_busy(tmp_path / "conv.db", "aetheria", within_seconds=600)
    assert not interactive_busy(tmp_path / "conv.db", "vett", within_seconds=600)
