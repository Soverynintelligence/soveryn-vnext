"""deliberate_share tool — queue insertion, agent-aware rate limits."""
from __future__ import annotations
import pytest

from soveryn.app.messenger.store import MessengerStore
from soveryn.agents.messenger_tool import build_deliberate_share_tool


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
