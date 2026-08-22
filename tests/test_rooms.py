"""Group room v0 — open + ask_peer + collab chips."""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.citizens.registry import Citizen, connect, register
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore
from soveryn.rooms.store import MESSAGED_MARKER, open_room


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok",
        finish_reason="stop",
        tool_calls=None,
        usage=None,
        raw={},
    )


@pytest.fixture
def room_app(tmp_path: Path, fake_chat, monkeypatch):
    db = tmp_path / "citizens.db"
    with connect(db) as conn:
        for cid, name in (
            ("aetheria", "Aetheria"),
            ("vett", "V.E.T.T."),
            ("jon", "Jon"),
        ):
            try:
                register(
                    conn,
                    Citizen(
                        id=cid,
                        display_name=name,
                        workspace_path=str(tmp_path / "desks" / cid),
                    ),
                )
            except Exception:
                # jon may not be a citizen — only aetheria/vett required
                if cid == "jon":
                    pass
                else:
                    raise

    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["CITIZENS_DB"] = str(db)
    monkeypatch.setenv("SOVERYN_CITIZENS_DB", str(db))
    # Point data root for room sidecars
    state = app.extensions.setdefault("soveryn", {})
    class _Env:
        data_root = tmp_path / "data"
    (_Env.data_root).mkdir(parents=True, exist_ok=True)
    state["env"] = _Env()
    state["conv_store"] = conv
    return app, conv, tmp_path


def test_open_room_and_ask_peer(room_app):
    app, conv, tmp_path = room_app
    client = app.test_client()

    dm = conv.new_session("aetheria", title="dm")
    resp = client.post(
        "/api/rooms/open",
        json={"peer": "vett", "dm_session_id": dm},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.get_json()
    assert data["ok"]
    sid = data["room"]["session_id"]
    assert data["room"]["peer"] == "vett"

    ask = client.post(
        f"/api/rooms/{sid}/ask_peer",
        json={"brief": "Check the founding entry quotes."},
    )
    assert ask.status_code == 200, ask.get_data(as_text=True)
    body = ask.get_json()
    assert body["ok"]
    assert body["event"]["peer"] == "vett"
    assert body["routing"]["commission_id"]

    # Room history has messaged marker
    hist = conv.load_history(sid)
    sys_turns = [t for t in hist if t.role == "system"]
    assert any(MESSAGED_MARKER.format(peer="vett") in t.content for t in sys_turns)

    # DM also got a chip line
    dm_hist = conv.load_history(dm)
    assert any(MESSAGED_MARKER.format(peer="vett") in t.content for t in dm_hist if t.role == "system")

    collabs = client.get(f"/api/rooms/collabs?dm_session_id={dm}")
    assert collabs.status_code == 200
    c = collabs.get_json()
    assert c["count"] >= 1
    assert c["collabs"][0]["peer"] == "vett"


def test_room_page_ok(room_app):
    app, _, _ = room_app
    client = app.test_client()
    r = client.get("/room?peer=vett")
    assert r.status_code == 200
    assert b"data-ask-peer" in r.data


def test_messages_page_ok(room_app):
    app, _, _ = room_app
    client = app.test_client()
    r = client.get("/messages")
    assert r.status_code == 200
    assert b"Messages" in r.data
    assert b"Aetheria" in r.data


def test_record_house_post_collab_chip(room_app):
    from soveryn.rooms.store import record_house_post_collab

    app, conv, tmp_path = room_app
    dm = conv.new_session("aetheria", title="dm")
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    ev = record_house_post_collab(
        conv,
        data_root=data_root,
        from_id="aetheria",
        to_id="vett",
        body="Please check the quotes on founding.",
        dm_session_id=dm,
    )
    assert ev is not None
    assert ev["peer"] == "vett"
    dm_hist = conv.load_history(dm)
    assert any("Messaged Vett" in t.content for t in dm_hist if t.role == "system")
    room_hist = conv.load_history(ev["room_session_id"])
    assert any("[To Vett]" in t.content for t in room_hist if t.role == "assistant")
