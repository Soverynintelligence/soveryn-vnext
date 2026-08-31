""" /chat is not a desk console — it redirects to Messages. """

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})


@pytest.fixture
def client(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()


def test_chat_route_redirects_to_messages(client):
    resp = client.get("/chat")
    assert resp.status_code == 302
    assert resp.headers.get("Location", "").endswith("/messages")


def test_chat_agent_query_redirects_into_that_thread(client):
    resp = client.get("/chat?agent=kernel")
    assert resp.status_code == 302
    assert "/messages/kernel" in resp.headers.get("Location", "")


def test_folded_agents_are_not_messages_contacts(client):
    body = client.get("/messages", follow_redirects=True).data.decode("utf-8")
    assert 'id: "aetheria"' in body
    assert 'id: "kernel"' in body
    assert 'id: "eve"' in body
    assert 'id: "vett"' not in body
    assert 'id: "scotty"' not in body
    assert 'id: "grok"' not in body
