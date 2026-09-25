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
    assert w == {"ok": True, "open": False, "entries": []}


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
