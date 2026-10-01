"""Unit tests for read_overnight_brief (Critic/Scout → Aetheria commissions)."""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.teammates_brief_tools import register_teammates_brief_tools
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


@pytest.fixture
def store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "conv.db")


@pytest.fixture
def registry(store: ConversationStore) -> ToolRegistry:
    reg = ToolRegistry(audit_hook=lambda _event: None)
    register_teammates_brief_tools(reg, conv_store=store, owner_agent="aetheria")
    return reg


def test_empty_inbox_returns_ok_no_briefs(registry: ToolRegistry):
    out = registry.invoke("aetheria", "read_overnight_brief", {"who": "critic"})
    assert out["ok"] is True
    assert out["briefs"] == []
    assert "No overnight" in out["note"]


def test_reads_latest_assistant_brief(registry: ToolRegistry, store: ConversationStore):
    sid = store.new_session("t_critic", title="Critic · overnight")
    store.save_turn(sid, "t_critic", "assistant", "FINDING: Funnel cookie missing expiry.")
    out = registry.invoke(
        "aetheria", "read_overnight_brief", {"who": "critic", "limit": 1}
    )
    assert out["ok"] is True
    assert out["count"] == 1
    assert "Funnel cookie" in out["briefs"][0]["content"]
    assert "kernel" in out["routing_hint"]
    assert out["session_id"] == sid


def test_scout_alias_and_bad_who(registry: ToolRegistry, store: ConversationStore):
    sid = store.new_session("t_scout", title="Scout · overnight")
    store.save_turn(sid, "t_scout", "assistant", "Scout saw X trending.")
    out = registry.invoke("aetheria", "read_overnight_brief", {"who": "scout"})
    assert out["ok"] is True
    assert "trending" in out["briefs"][0]["content"]
    with pytest.raises(ToolArgError):
        registry.invoke("aetheria", "read_overnight_brief", {"who": "marketer"})
