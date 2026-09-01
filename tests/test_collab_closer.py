"""Collab closer — working chips die with the ticket (2026-08-31 spec)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from soveryn.citizens import commissions
from soveryn.citizens.census import DESK_DIRS
from soveryn.citizens.registry import Citizen, connect, register
from soveryn.citizens.runtime import execute_claimed
from soveryn.memory.conversation_store import ConversationStore
from soveryn.rooms.store import (
    CLOSED_MARKER,
    COLLAB_TTL_SECONDS,
    collab_is_active,
    close_collab_for_commission,
    find_open_collab,
    load_room,
    overlay_collab_commission_states,
    record_house_post_collab,
    rooms_root,
)


@pytest.fixture
def env(tmp_path: Path):
    db = tmp_path / "citizens.db"
    work = tmp_path / "desks"
    for cid in ("aetheria", "eve", "kernel"):
        desk = work / cid
        for d in DESK_DIRS:
            (desk / d).mkdir(parents=True, exist_ok=True)
    with connect(db) as conn:
        for cid, name in (
            ("aetheria", "Aetheria"),
            ("eve", "Eve"),
            ("kernel", "Kernel"),
        ):
            register(
                conn,
                Citizen(
                    id=cid,
                    display_name=name,
                    workspace_path=str(work / cid),
                ),
            )
    conv = ConversationStore(tmp_path / "conv.db")
    data_root = tmp_path / "data"
    data_root.mkdir()
    return conv, data_root, db


def _open_kernel(env, cid="cid-k1"):
    conv, data_root, _db = env
    dm = conv.new_session("aetheria", title="[m] Aetheria")
    ev = record_house_post_collab(
        conv,
        data_root=data_root,
        from_id="aetheria",
        to_id="kernel",
        body="Docs pass.",
        dm_session_id=dm,
        commission_id=cid,
    )
    return dm, ev


def test_open_collab_with_commission_is_working(env):
    dm, ev = _open_kernel(env)
    assert ev is not None
    assert ev["state"] == "working"
    assert ev["commission_id"] == "cid-k1"
    assert collab_is_active(ev)


def test_mark_working_without_commission_id_does_not_chip(env):
    conv, data_root, _db = env
    dm = conv.new_session("aetheria", title="dm")
    ev = record_house_post_collab(
        conv,
        data_root=data_root,
        from_id="aetheria",
        to_id="eve",
        body="Nested chat, no ticket.",
        dm_session_id=dm,
        mark_working=True,
    )
    assert ev is not None
    assert ev.get("state") != "working"
    assert not ev.get("commission_id")
    assert not collab_is_active(ev)


def test_close_collab_writes_done_and_closed_marker(env):
    conv, data_root, db = env
    dm, ev = _open_kernel(env)
    with connect(db) as conn:
        commissions.enqueue(conn, "kernel", "Docs pass.", at="2026-08-31T12:00:00Z")
        # Use the chip's id as a real ticket so overlay could match; closer
        # does not require the row — sidecar + DM line are the product.
    closed = close_collab_for_commission(
        conv,
        data_root=data_root,
        commission_id="cid-k1",
        ok=True,
    )
    assert closed is not None
    room = load_room(data_root, ev["room_session_id"])
    states = [
        e.get("state")
        for e in (room.get("events") or [])
        if e.get("commission_id") == "cid-k1"
    ]
    assert "done" in states
    assert "working" not in states
    marker = CLOSED_MARKER.format(peer="kernel")
    dm_hist = conv.load_history(dm)
    assert any(marker in (t.content or "") and "done" in (t.content or "") for t in dm_hist)
    # Idempotent
    close_collab_for_commission(
        conv, data_root=data_root, commission_id="cid-k1", ok=True
    )
    again = [t for t in conv.load_history(dm) if marker in (t.content or "")]
    assert len(again) == 1


def test_close_collab_fail_path(env):
    conv, data_root, _db = env
    dm, ev = _open_kernel(env, cid="cid-fail")
    close_collab_for_commission(
        conv, data_root=data_root, commission_id="cid-fail", ok=False
    )
    room = load_room(data_root, ev["room_session_id"])
    hit = next(
        e for e in room["events"] if e.get("commission_id") == "cid-fail"
    )
    assert hit["state"] == "failed"
    marker = CLOSED_MARKER.format(peer="kernel")
    assert any(
        marker in (t.content or "") and "failed" in (t.content or "")
        for t in conv.load_history(dm)
    )


def test_runtime_complete_closes_without_collabs_get(env):
    conv, data_root, db = env
    dm = conv.new_session("aetheria", title="[m] Aetheria")
    with connect(db) as conn:
        cid = commissions.enqueue(
            conn, "kernel", "Fix the dump.", at="2026-08-31T12:00:00Z"
        )
        claimed = commissions.claim(
            conn, "kernel", worker="test", at="2026-08-31T12:00:01Z"
        )
    record_house_post_collab(
        conv,
        data_root=data_root,
        from_id="aetheria",
        to_id="kernel",
        body="Fix the dump.",
        dm_session_id=dm,
        commission_id=cid,
    )

    def process(citizen_id, body, commission_id):
        return "patched."

    execute_claimed(
        db,
        claimed,
        process_fn=process,
        at="2026-08-31T12:00:02Z",
        conv_store=conv,
        data_root=data_root,
    )
    assert find_open_collab(data_root, dm_session_id=dm, peer="kernel") is None
    marker = CLOSED_MARKER.format(peer="kernel")
    assert any(marker in (t.content or "") for t in conv.load_history(dm))
    sidecar = json.loads(
        next(rooms_root(data_root).glob("*.json")).read_text(encoding="utf-8")
    )
    working = [
        e
        for e in sidecar.get("events") or []
        if e.get("commission_id") == cid and e.get("state") == "working"
    ]
    assert working == []


def test_second_open_reuses_live_commission(env):
    conv, data_root, db = env
    dm = conv.new_session("aetheria", title="dm")
    with connect(db) as conn:
        cid = commissions.enqueue(
            conn, "kernel", "First ask.", at="2026-08-31T12:00:00Z"
        )
        commissions.claim(conn, "kernel", worker="w", at="2026-08-31T12:00:01Z")
    record_house_post_collab(
        conv,
        data_root=data_root,
        from_id="aetheria",
        to_id="kernel",
        body="First ask.",
        dm_session_id=dm,
        commission_id=cid,
    )
    hit = find_open_collab(
        data_root, dm_session_id=dm, peer="kernel", citizens_db=db
    )
    assert hit is not None
    assert hit["commission_id"] == cid


def test_cos_relay_dedupes_same_source(env):
    from soveryn.citizens.runtime import _enqueue_cos_summary

    conv, data_root, db = env
    dm = conv.new_session("aetheria", title="dm")
    cid = "src-abc"
    record_house_post_collab(
        conv,
        data_root=data_root,
        from_id="aetheria",
        to_id="kernel",
        body="Docs.",
        dm_session_id=dm,
        commission_id=cid,
    )
    a = _enqueue_cos_summary(
        db,
        peer="kernel",
        source_commission_id=cid,
        task="Docs.",
        result_text="ok",
        ok=True,
        data_root=data_root,
        at="2026-08-31T12:01:00Z",
    )
    b = _enqueue_cos_summary(
        db,
        peer="kernel",
        source_commission_id=cid,
        task="Docs.",
        result_text="ok again",
        ok=True,
        data_root=data_root,
        at="2026-08-31T12:02:00Z",
    )
    assert a
    assert b is None
    with connect(db) as conn:
        rows = commissions.for_citizen(conn, "aetheria")
    relays = [r for r in rows if "source_commission: src-abc" in (r.get("body") or "")]
    assert len(relays) == 1


def test_overlay_ttl_expires_working_chip(env):
    conv, data_root, db = env
    dm, ev = _open_kernel(env, cid="cid-old")
    sid = ev["room_session_id"]
    path = rooms_root(data_root) / f"{sid}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    old = "2026-08-31T10:00:00Z"
    for e in data["events"]:
        if e.get("commission_id") == "cid-old":
            e["at"] = old
    path.write_text(json.dumps(data), encoding="utf-8")
    now = datetime(2026, 8, 31, 11, 0, 0, tzinfo=timezone.utc)
    assert now - datetime(2026, 8, 31, 10, 0, 0, tzinfo=timezone.utc) > timedelta(
        seconds=COLLAB_TTL_SECONDS
    )
    out = overlay_collab_commission_states(
        [json.loads(path.read_text())["events"][0] | {"room_session_id": sid}],
        citizens_db=db,
        data_root=data_root,
        persist=True,
        now=now,
    )
    assert out[0]["state"] == "failed"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["events"][0]["state"] == "failed"


def test_collab_is_active_never_keeps_terminal():
    done = {"peer": "kernel", "state": "done", "at": "2026-08-31T18:00:00Z"}
    failed = {"peer": "kernel", "state": "failed", "at": "2026-08-31T18:00:00Z"}
    now = datetime(2026, 8, 31, 18, 10, tzinfo=timezone.utc)
    assert not collab_is_active(done, now=now)
    assert not collab_is_active(failed, now=now)


def test_read_collab_tool_returns_transcript(env):
    from soveryn.agents.direct_communication.read_collab import build_read_collab_tool

    conv, data_root, db = env
    dm, ev = _open_kernel(env, cid="cid-read")
    tool = build_read_collab_tool(
        conv_store=conv, data_root=data_root, citizens_db=db
    )
    out = tool.handler({"peer": "kernel", "commission_id": "cid-read"})
    assert out["ok"] is True
    assert out["state"] == "working"
    assert out["commission_id"] == "cid-read"
    assert out["room_session_id"] == ev["room_session_id"]
    assert isinstance(out.get("turns"), list)
    assert out["turns"]
