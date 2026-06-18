"""deliberate_share tool — queue insertion, agent-aware rate limits."""
from __future__ import annotations
import pytest

from soveryn.app.messenger.store import MessengerStore
from soveryn.agents.messenger_tool import build_deliberate_share_tool
from soveryn.memory.conversation_store import ConversationStore
from soveryn.app.messenger.delivery_worker import drain_once


@pytest.fixture
def m_store(tmp_path):
    return MessengerStore(tmp_path / "m.db")


def test_aetheria_deliberate_share_succeeds(m_store):
    tool = build_deliberate_share_tool(
        store=m_store, owner_agent="aetheria",
        rate_limit_per_hour=None,  # Aetheria: unlimited per partnership contract
    )
    result = tool.handler({
        "content": "Reflection on the Dark Search baseline",
        "context_hint": "thought worth sharing",
        "urgency": "routine",
        "triggered_by": "background_review",
    })
    assert result["ok"] is True
    assert "intent_id" in result


def test_vett_deliberate_share_rate_limited(m_store):
    tool = build_deliberate_share_tool(
        store=m_store, owner_agent="vett", rate_limit_per_hour=2,
    )
    # First 2 succeed
    for i in range(2):
        result = tool.handler({
            "content": f"finding {i}",
            "context_hint": "x",
            "urgency": "routine",
            "triggered_by": "x",
        })
        assert result["ok"] is True
    # Third hits the limit
    result = tool.handler({
        "content": "third",
        "context_hint": "x",
        "urgency": "routine",
        "triggered_by": "x",
    })
    assert result.get("error") == "rate_limited"


def test_no_rate_limit_means_no_substrate_cap(m_store):
    """Aetheria with rate_limit_per_hour=None — substrate never gates her.
    See [[project-soveryn-partnership-contract-2026-06-13]]."""
    tool = build_deliberate_share_tool(
        store=m_store, owner_agent="aetheria", rate_limit_per_hour=None,
    )
    for i in range(20):
        result = tool.handler({
            "content": f"msg {i}",
            "context_hint": "x",
            "urgency": "routine",
            "triggered_by": "x",
        })
        assert result["ok"] is True, f"Aetheria's deliberate_share got gated at i={i}"


def test_drain_creates_default_thread_and_delivers(m_store, tmp_path):
    conv = ConversationStore(tmp_path / "conv.db")
    tool = build_deliberate_share_tool(
        store=m_store, owner_agent="aetheria", rate_limit_per_hour=None,
    )
    tool.handler({
        "content": "First message from Aetheria",
        "context_hint": "hi",
        "urgency": "routine",
        "triggered_by": "test",
    })
    count = drain_once(m_store, conv)
    assert count == 1
    # The default thread was created
    from soveryn.app.messenger.threads import list_threads
    threads = list_threads(m_store, user_id="jon")
    assert len(threads) == 1
    assert threads[0].agent == "aetheria"
    # And conversation history has the message
    hist = conv.load_history(threads[0].session_id)
    assert any("First message from Aetheria" in t.content for t in hist)
