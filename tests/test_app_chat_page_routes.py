"""Tests for /chat page route (Phase 1: static skeleton)."""

import re
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


def test_chat_route_returns_html(client):
    resp = client.get("/chat")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert resp.headers.get("X-SOVERYN-UI-Source") == "vnext-native"


def test_chat_page_has_sidebar_marker(client):
    body = client.get("/chat").data.decode("utf-8")
    assert 'data-testid="sidebar"' in body


def test_chat_page_has_new_chat_button(client):
    body = client.get("/chat").data.decode("utf-8")
    assert 'data-testid="new-chat"' in body


def test_chat_page_has_agent_pills_for_active_agents(client):
    body = client.get("/chat").data.decode("utf-8").lower()
    for agent in ACTIVE_AGENTS:
        assert f'data-agent="{agent}"' in body


def test_chat_page_no_retired_agents(client):
    body = client.get("/chat").data.decode("utf-8").lower()
    for retired in ("scout", "vision", "tinker", "ares_llm"):
        assert retired not in body, f"retired {retired!r} leaked into chat page"


def test_chat_page_no_external_resources(client):
    body = client.get("/chat").data.decode("utf-8")
    assert re.findall(r'<script[^>]+src=["\']https?://', body) == []
    assert re.findall(r'<link[^>]+href=["\']https?://', body) == []


def test_chat_page_has_thread_marker(client):
    body = client.get("/chat").data.decode("utf-8")
    assert 'data-testid="thread"' in body


def test_chat_page_has_input_marker(client):
    body = client.get("/chat").data.decode("utf-8")
    assert 'data-testid="composer"' in body


def test_chat_page_has_thinking_placeholder_template(client):
    """The thinking-placeholder CSS class must exist so streaming bubbles can show
    'thinking…' before the first non-empty token."""
    body = client.get("/chat").data.decode("utf-8")
    assert "thinking-placeholder" in body
    assert "@keyframes" in body  # pulse animation lives somewhere in the styles


def test_chat_page_has_header_with_agent_identity_slot(client):
    body = client.get("/chat").data.decode("utf-8")
    assert 'data-testid="chat-header"' in body


def test_chat_page_has_streaming_toggle(client):
    body = client.get("/chat").data.decode("utf-8")
    assert 'data-testid="stream-toggle"' in body


def test_chat_page_reads_agent_from_query_string(client):
    body = client.get("/chat").data.decode("utf-8")
    assert "searchParams" in body or "URLSearchParams" in body


def test_chat_page_uses_fetch_for_streaming(client):
    """Streaming uses fetch + ReadableStream, not EventSource."""
    body = client.get("/chat").data.decode("utf-8")
    assert "ReadableStream" in body or "getReader" in body
    assert "EventSource" not in body, "EventSource doesn't POST; must use fetch"


def test_chat_page_supports_abort(client):
    body = client.get("/chat").data.decode("utf-8")
    assert "AbortController" in body


def test_chat_page_posts_to_chat_stream(client):
    body = client.get("/chat").data.decode("utf-8")
    assert "/chat_stream" in body


def test_chat_page_posts_to_chat_sync(client):
    body = client.get("/chat").data.decode("utf-8")
    assert '"/chat"' in body or "'/chat'" in body


def test_chat_page_groups_history_by_date(client):
    body = client.get("/chat").data.decode("utf-8")
    # The grouping logic uses these labels
    for label in ("Today", "Yesterday", "Previous 7 days"):
        assert label in body


def test_chat_page_fetches_sessions_on_agent_change(client):
    body = client.get("/chat").data.decode("utf-8")
    assert "/sessions?agent=" in body


def test_chat_page_thread_has_aria_live(client):
    body = client.get("/chat").data.decode("utf-8")
    assert 'aria-live="polite"' in body or "aria-live='polite'" in body


def test_chat_composer_input_has_label(client):
    body = client.get("/chat").data.decode("utf-8")
    assert "aria-label" in body
