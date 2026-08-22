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
    assert b"/messages/aetheria" in r.data or b"messages/" in r.data


def test_message_thread_page_ok(room_app):
    app, _, _ = room_app
    client = app.test_client()
    r = client.get("/messages/aetheria")
    assert r.status_code == 200
    assert b"data-thread" in r.data
    assert b"data-send" in r.data


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
        commission_id="cid-test-1",
    )
    assert ev is not None
    assert ev["peer"] == "vett"
    assert ev.get("commission_id") == "cid-test-1"
    dm_hist = conv.load_history(dm)
    assert any("Messaged Vett" in t.content for t in dm_hist if t.role == "system")
    assert any("working" in t.content for t in dm_hist if t.role == "system")
    room_hist = conv.load_history(ev["room_session_id"])
    assert any("[To Vett]" in t.content for t in room_hist if t.role == "assistant")
    assert any("Commissioned Vett" in t.content for t in room_hist if t.role == "system")


def test_project_commission_result_into_room(room_app):
    from soveryn.rooms.store import project_commission_result, record_house_post_collab

    app, conv, tmp_path = room_app
    dm = conv.new_session("aetheria", title="dm")
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    cid = "cid-reply-1"
    ev = record_house_post_collab(
        conv,
        data_root=data_root,
        from_id="aetheria",
        to_id="vett",
        body="Research liner options.",
        dm_session_id=dm,
        commission_id=cid,
    )
    assert ev is not None
    reply = project_commission_result(
        conv,
        data_root=data_root,
        citizen_id="vett",
        commission_id=cid,
        result_text="Liner A is best for kidney ponds.",
        ok=True,
    )
    assert reply is not None
    assert reply["type"] == "peer_reply"
    room_hist = conv.load_history(ev["room_session_id"])
    assert any(
        "[From Vett]" in t.content and "Liner A" in t.content
        for t in room_hist
        if t.role == "system"
    )
    dm_hist = conv.load_history(dm)
    assert any("replied" in t.content.lower() for t in dm_hist if t.role == "system")


def test_cos_relays_peer_result_into_jon_dm(room_app):
    """When a peer finishes, Aetheria must put the substance in the 1:1 DM."""
    from soveryn.rooms.store import (
        deliver_peer_result_to_jon,
        open_room,
        project_commission_result,
        record_house_post_collab,
    )

    app, conv, tmp_path = room_app
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    dm = conv.new_session("aetheria", title="[m] Aetheria — test")
    cid = "cid-relay-1"
    record_house_post_collab(
        conv,
        data_root=data_root,
        from_id="aetheria",
        to_id="vett",
        body="Research fountain maintenance pricing.",
        dm_session_id=dm,
        commission_id=cid,
    )
    ev = project_commission_result(
        conv,
        data_root=data_root,
        citizen_id="vett",
        commission_id=cid,
        result_text=(
            "Aquascape annual service ~$450–$900 depending on region; "
            "The Pond Guy lists seasonal start-up packages from $299."
        ),
        ok=True,
    )
    assert ev is not None
    dm_hist = conv.load_history(dm)
    assistant = [t for t in dm_hist if t.role == "assistant"]
    assert any("bringing it back" in t.content for t in assistant)
    assert any("$450" in t.content or "Pond Guy" in t.content for t in assistant)


def test_add_peer_grows_shared_group(room_app):
    """Same DM should grow one multi-peer room (Vett then Eve), not two rooms."""
    from soveryn.rooms.store import add_peer_to_room, open_room, room_peers

    app, conv, tmp_path = room_app
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    dm = conv.new_session("aetheria", title="dm-multi")
    r1 = open_room(conv, data_root=data_root, peer="vett", dm_session_id=dm)
    assert room_peers(r1) == ["vett"]
    r2 = open_room(conv, data_root=data_root, peer="eve", dm_session_id=dm)
    assert r2["session_id"] == r1["session_id"]
    assert set(room_peers(r2)) == {"vett", "eve"}
    r3 = add_peer_to_room(
        conv, data_root=data_root, session_id=r1["session_id"], peer="scotty"
    )
    assert set(room_peers(r3)) == {"vett", "eve", "scotty"}
    hist = conv.load_history(r1["session_id"])
    assert any("Added Eve" in t.content for t in hist if t.role == "system")
    assert any("Added Scotty" in t.content for t in hist if t.role == "system")


def test_house_post_send_commissions_peer(room_app, monkeypatch):
    """Aetheria house_post_send to Vett must enqueue a commission (wake path)."""
    from soveryn.citizens import commissions
    from soveryn.citizens.registry import connect
    from soveryn.platform.house_post_tools import register_house_post_tools
    from soveryn.platform.tools.registry import ToolRegistry
    from soveryn.rooms import context as room_ctx

    app, conv, tmp_path = room_app
    db = Path(app.config["CITIZENS_DB"])
    monkeypatch.setenv("SOVERYN_CITIZENS_DB", str(db))
    data_root = tmp_path / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    dm = conv.new_session("aetheria", title="dm-tool")

    reg = ToolRegistry()
    register_house_post_tools(reg, owner_agent="aetheria")

    with app.app_context():
        app.extensions["soveryn"]["conv_store"] = conv
        tok_dm = room_ctx.dm_session_id.set(dm)
        tok_root = room_ctx.data_root.set(data_root)
        try:
            result = reg.invoke(
                "aetheria",
                "house_post_send",
                {"to_id": "vett", "body": "Research pond liner options.", "kind": "request"},
            )
        finally:
            room_ctx.dm_session_id.reset(tok_dm)
            room_ctx.data_root.reset(tok_root)

    assert result.get("ok") is True, result
    assert result.get("commissioned") is True
    assert result.get("commission_id")
    with connect(db) as conn:
        row = commissions.get(conn, result["commission_id"])
    assert row is not None
    assert row["citizen_id"] == "vett"
    assert row["state"] in ("queued", "running", "done")
    dm_hist = conv.load_history(dm)
    assert any("Messaged Vett" in t.content for t in dm_hist if t.role == "system")
