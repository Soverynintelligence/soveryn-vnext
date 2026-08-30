"""Kernel Messages turns enqueue instead of owning the SSE thread."""

from __future__ import annotations

from pathlib import Path

from soveryn.app.deferred_chat import format_messages_turn, parse_messages_turn
from soveryn.citizens.registry import Citizen, connect, register
from soveryn.citizens import commissions
from soveryn.memory.conversation_store import ConversationStore


def test_parse_messages_turn_round_trip():
    body = format_messages_turn("sess-1", "fix the seats")
    parsed = parse_messages_turn(body)
    assert parsed == ("sess-1", "fix the seats\n")
    assert parse_messages_turn("plain commission") is None


def test_kernel_chat_stream_defers_when_citizens_db_ready(tmp_path, monkeypatch):
    from soveryn.agents.loop import AgentLoop
    from soveryn.app.startup import create_app
    from soveryn.config.runtime import ACTIVE_AGENTS
    from soveryn.inference.llama_server_client import ChatResponse, StreamChunk
    import json

    conv = ConversationStore(tmp_path / "conv.db")
    sid = conv.new_session("kernel", title="k")
    stream_calls = []

    def stream_fn(request, server, timeout=120.0):
        stream_calls.append(1)
        def _g():
            yield StreamChunk(delta="nope", finish_reason="stop", raw={})
        return _g()

    fake_chat = lambda req, server, timeout=60: ChatResponse(
        content="done in bg", finish_reason="stop", tool_calls=None, usage=None, raw={}
    )
    loops = {
        n: AgentLoop(n, conv, chat_fn=fake_chat, stream_fn=stream_fn)
        for n in ACTIVE_AGENTS
    }
    db = tmp_path / "citizens.db"
    with connect(db) as conn:
        register(conn, Citizen(id="kernel", display_name="Kernel"))
        register(conn, Citizen(id="aetheria", display_name="Aetheria"))
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["TESTING"] = True
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    app.config["DEFER_CHAT"] = True
    app.config["CITIZENS_DB"] = str(db)
    client = app.test_client()
    resp = client.post(
        "/chat_stream",
        data=json.dumps({"agent": "kernel", "session_id": sid, "message": "mend it"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "deferred" in body
    assert "This thread stays yours" in body
    assert stream_calls == []
    turns = conv.load_history(sid)
    assert turns[-1].role == "user"
    assert turns[-1].content == "mend it"
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT body, state FROM commissions WHERE citizen_id='kernel'"
        ).fetchall()
    assert len(rows) == 1
    assert "[MESSAGES_TURN]" in rows[0]["body"]


def test_try_defer_skips_aetheria(tmp_path):
    from soveryn.agents.loop import AgentLoop
    from soveryn.app.deferred_chat import try_defer_chat
    from soveryn.app.startup import create_app
    from soveryn.config.runtime import ACTIVE_AGENTS
    from soveryn.inference.llama_server_client import ChatResponse

    conv = ConversationStore(tmp_path / "conv.db")
    sid = conv.new_session("aetheria", title="a")
    fake_chat = lambda req, server, timeout=60: ChatResponse(
        content="x", finish_reason="stop", tool_calls=None, usage=None, raw={}
    )
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    db = tmp_path / "citizens.db"
    with connect(db) as conn:
        register(conn, Citizen(id="aetheria", display_name="Aetheria"))
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["DEFER_CHAT"] = True
    app.config["CITIZENS_DB"] = str(db)
    with app.app_context():
        assert try_defer_chat(
            agent="aetheria",
            session_id=sid,
            message="hi",
            state={"conv_store": conv},
        ) is None
    assert list(conv.load_history(sid)) == []


def test_skip_user_save_does_not_duplicate(tmp_path):
    from soveryn.agents.loop import AgentLoop
    from soveryn.inference.llama_server_client import ChatResponse

    conv = ConversationStore(tmp_path / "conv.db")
    sid = conv.new_session("kernel", title="k")
    conv.save_turn(sid, "kernel", "user", "hello", source="deferred")
    loop = AgentLoop(
        "kernel",
        conv,
        chat_fn=lambda req, server, timeout=60: ChatResponse(
            content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={}
        ),
    )
    loop.process_message(sid, "hello", source="deferred", skip_user_save=True)
    users = [t for t in conv.load_history(sid) if t.role == "user"]
    assistants = [t for t in conv.load_history(sid) if t.role == "assistant"]
    assert len(users) == 1
    assert len(assistants) == 1
