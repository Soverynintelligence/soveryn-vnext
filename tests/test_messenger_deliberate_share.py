"""deliberate_share tool — grammar emission, ledger write, rate limits."""
from __future__ import annotations
import sqlite3
import pytest

from soveryn.app.messenger.store import MessengerStore
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.messenger_tool import build_deliberate_share_tool
from soveryn.memory.conversation_store import ConversationStore
from soveryn.app.messenger.delivery_worker import drain_once


@pytest.fixture
def m_store(tmp_path):
    return MessengerStore(tmp_path / "m.db")


@pytest.fixture
def l_store(tmp_path):
    return LatticeStore(tmp_path / "l.db")


def _args(**overrides):
    base = {
        "content": "Reflection on the Dark Search baseline",
        "context_hint": "thought worth sharing",
        "urgency": "routine",
        "why": "this reframes how I read the whole arc",
        "stance": "surfacing-tension",
        "trigger": "the baseline number you just read me",
    }
    base.update(overrides)
    return base


def test_aetheria_deliberate_share_succeeds(m_store, l_store):
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
    result = tool.handler(_args())
    assert result["ok"] is True
    assert "intent_id" in result
    assert "mark_node_id" in result


def test_vett_deliberate_share_rate_limited(m_store, l_store):
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="vett",
        rate_limit_per_hour=2,
    )
    for i in range(2):
        assert tool.handler(_args(content=f"finding {i}"))["ok"] is True
    assert tool.handler(_args(content="third")).get("error") == "rate_limited"


def test_no_rate_limit_means_no_substrate_cap(m_store, l_store):
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
    for i in range(20):
        assert tool.handler(_args(content=f"msg {i}"))["ok"] is True, f"gated at {i}"


def test_share_writes_ledger_node_and_edge(m_store, l_store):
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
    result = tool.handler(_args(stance="marking-delight"))
    mark = l_store.get_node(result["mark_node_id"])
    assert mark.type == "deliberate_share"
    assert mark.intent == "marking-delight"
    with sqlite3.connect(str(l_store.db_path)) as con:
        con.row_factory = sqlite3.Row
        edges = con.execute("SELECT * FROM edges WHERE relationship='triggered_by'").fetchall()
    assert len(edges) == 1


def test_why_and_stance_stored_in_queue(m_store, l_store):
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
    result = tool.handler(_args(why="the honest reason", stance="offering"))
    with m_store._conn() as con:
        row = con.execute(
            "SELECT why, stance FROM m_outbound_queue WHERE intent_id=?",
            (result["intent_id"],),
        ).fetchone()
    assert row["why"] == "the honest reason"
    assert row["stance"] == "offering"


def test_drain_creates_default_thread_and_delivers(m_store, l_store, tmp_path):
    conv = ConversationStore(tmp_path / "conv.db")
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
    tool.handler(_args(
        content="First message from Aetheria",
        context_hint="hi",
        urgency="routine",
    ))
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
