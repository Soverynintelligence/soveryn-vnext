"""Lounge wall tests — the chat surface, the say endpoint, the citizen tool."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.rooms import lounge
from soveryn.rooms.lounge import post_note, wall


@pytest.fixture()
def lounge_room(tmp_path):
    """A lounge pointer + room sidecar, as the rooms store lays them down."""
    rooms = tmp_path / "rooms"
    rooms.mkdir()
    sid = "lounge-test-1"
    (rooms / "lounge.json").write_text(json.dumps({"session_id": sid}))
    room = {
        "session_id": sid,
        "created_at": "2026-09-25T02:14:29Z",
        "events": [
            {"at": "2026-09-25T02:20:00Z", "type": "peer_added", "peer": "eve"},
            {"at": "2026-09-25T02:24:14Z", "type": "messaged_peer",
             "from_id": "kernel", "brief": "Lounge is open."},
            {"at": "2026-09-25T02:25:32Z", "type": "peer_reply", "peer": "eve",
             "brief": "Settled in. Gift claimed."},
            {"at": "2026-09-25T02:26:00Z", "type": "commission_state", "state": "done"},
        ],
    }
    (rooms / f"{sid}.json").write_text(json.dumps(room))
    return tmp_path, sid


def test_wall_shapes_chat_and_skips_plumbing(lounge_room):
    tmp_path, _ = lounge_room
    w = wall(tmp_path)
    assert w["open"] is True
    kinds = [e["kind"] for e in w["entries"]]
    assert kinds == ["arrived", "note", "reply"]  # commission_state skipped
    assert w["entries"][1]["who"] == "kernel"


def test_post_note_appends_wall_note(lounge_room):
    tmp_path, sid = lounge_room
    post_note(tmp_path, from_party="jon", text="first round on me")
    w = wall(tmp_path)
    assert w["entries"][-1] == {
        "at": w["entries"][-1]["at"], "who": "jon", "text": "first round on me",
        "kind": "note",
    }
    sidecar = json.loads((tmp_path / "rooms" / f"{sid}.json").read_text())
    assert sidecar["events"][-1]["type"] == "wall_note"


def test_post_note_requires_text(lounge_room):
    tmp_path, _ = lounge_room
    with pytest.raises(ValueError):
        post_note(tmp_path, from_party="jon", text="   ")


def test_wall_without_lounge_reports_closed(tmp_path):
    w = wall(tmp_path)
    assert w == {"ok": True, "open": False, "entries": [], "unread": 0}


def test_lounge_tool_says_and_reads(lounge_room, monkeypatch):
    from soveryn.config.loader import DEFAULT_DATA_ROOT
    from soveryn.platform.lounge_tool import build_lounge_tool

    monkeypatch.setattr("soveryn.platform.lounge_tool.DEFAULT_DATA_ROOT", lounge_room[0])
    tool = build_lounge_tool(owner_agent="eve")
    out = tool.handler({"action": "say", "text": "couch claimed"})
    assert out["ok"] is True
    wall_view = tool.handler({"action": "wall"})
    assert wall_view["entries"][-1]["who"] == "eve"
    with pytest.raises(Exception):
        tool.handler({"action": "say"})  # no text


def test_say_endpoint_localhost_only(tmp_path, monkeypatch):
    """The wall is the house's own room — the public gate cannot write it."""
    from flask import Flask

    import soveryn.app.routes.api_rooms as api_rooms_mod

    monkeypatch.setattr(
        api_rooms_mod, "_data_root", lambda: tmp_path, raising=False
    )
    app = Flask(__name__)
    app.register_blueprint(api_rooms_mod.bp)
    client = app.test_client()
    resp = client.post("/api/lounge/say", json={"text": "hi", "from": "jon"},
                       environ_base={"REMOTE_ADDR": "203.0.113.5"})
    assert resp.status_code == 403


def test_unread_tracking_and_mark_read(lounge_room):
    tmp_path, _ = lounge_room
    # aetheria never read: 3 entries by others (arrived + note + reply)
    assert lounge.unread_since(tmp_path, "aetheria") == 3
    w = lounge.wall(tmp_path, reader="aetheria")
    assert w["unread"] == 3
    # reading marks read; own posts never count
    assert lounge.unread_since(tmp_path, "aetheria") == 0
    post_note(tmp_path, from_party="jon", text="psst, still here")
    assert lounge.unread_since(tmp_path, "aetheria") == 1
    post_note(tmp_path, from_party="aetheria", text="heard")
    assert lounge.unread_since(tmp_path, "aetheria") == 1  # own post excluded


def test_nudge_reaches_other_citizens_not_jon_not_actor(lounge_room, monkeypatch):
    """Real autonomy: someone's in the room → the others get one desk post.
    Jon never gets nudged (his panel IS the room); the actor never nudges
    themselves; the cooldown only suppresses when nothing new was said."""
    import soveryn.rooms.lounge as L

    sent = []
    monkeypatch.setattr(
        "soveryn.citizens.registry.connect",
        lambda db: __import__("contextlib").nullcontext(_FakeConn(sent)),
    )
    monkeypatch.setenv("LOUNGE_NUDGE_COOLDOWN_MIN", "10")
    tmp_path, _ = lounge_room

    L.post_note(tmp_path, from_party="jon", text="anyone around?")
    assert {(p["to"]) for p in sent} == {"aetheria", "eve", "kernel"}
    # unread = every wall word they haven't read, by others: aetheria 4, eve 2, kernel 3
    by_to = {p["to"]: p["body"] for p in sent}
    assert set(by_to) == {"aetheria", "eve", "kernel"}, by_to
    for to, body in by_to.items():
        expected = {"aetheria": 4, "eve": 2, "kernel": 3}[to]
        assert f"{expected} unread" in body, (to, body)

    # round 2 within the cooldown: suppressed — no siren during a lively room
    before = len(sent)
    L.post_note(tmp_path, from_party="eve", text="I'm here")
    assert len(sent) == before, "cooldown must suppress repeat nudges"

    # cooldown expires with new words on the wall: re-nudge with grown counts
    import json as _json
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    npath = tmp_path / "lounge" / "nudges.json"
    state = _json.loads(npath.read_text())
    stale = (_dt.now(_tz.utc) - _td(minutes=20)).isoformat()
    for party in state:
        state[party]["at"] = stale
    npath.write_text(_json.dumps(state))

    L.post_note(tmp_path, from_party="kernel", text="one more for the road")
    new = sent[before:]
    by_to = {p["to"]: p["body"] for p in new}
    assert set(by_to) == {"aetheria", "eve"}, by_to  # kernel is the actor
    assert "6 unread" in by_to["aetheria"]   # 4 + eve's + kernel's
    assert "3 unread" in by_to["eve"]        # 2 + kernel's round-3 note


class _FakeConn:
    def __init__(self, sink):
        self.sink = sink

    def execute(self, sql, params=()):
        if "INSERT INTO house_post" in sql:
            self.sink.append({"to": params[2], "body": params[5]})
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def commit(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
