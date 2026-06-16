"""mark_share — Aetheria's LIVE (in-conversation) intent-mark tool.

The live sibling of deliberate_share (async/messenger). Same grammar
(why/stance/trigger) and same ledger writer (record_intent), but for the
live surface: no delivery fields, channel="live".
"""
from __future__ import annotations
import sqlite3
import pytest

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.aetheria.intent_mark import build_mark_share_tool


@pytest.fixture
def l_store(tmp_path):
    return LatticeStore(tmp_path / "l.db")


def _args(**overrides):
    base = {
        "content": "That result is genuinely beautiful.",
        "why": "I want you to know this landed, not just register it.",
        "stance": "marking-delight",
        "trigger": "the baseline you just read me",
    }
    base.update(overrides)
    return base


def test_mark_share_writes_live_ledger_node_and_edge(l_store):
    tool = build_mark_share_tool(lattice_store=l_store, owner_agent="aetheria")
    res = tool.handler(_args(stance="marking-delight"))
    assert res["ok"] is True
    mark = l_store.get_node(res["mark_node_id"])
    assert mark.type == "deliberate_share"
    assert mark.intent == "marking-delight"
    assert mark.provenance["channel"] == "live"           # the live-surface marker
    assert mark.provenance["why"] == _args()["why"]
    with sqlite3.connect(str(l_store.db_path)) as con:
        con.row_factory = sqlite3.Row
        edges = con.execute(
            "SELECT * FROM edges WHERE relationship='triggered_by'"
        ).fetchall()
    assert len(edges) == 1
    assert edges[0]["source_id"] == res["mark_node_id"]


def test_mark_share_surfaces_why_stance_in_result(l_store):
    tool = build_mark_share_tool(lattice_store=l_store, owner_agent="aetheria")
    res = tool.handler(_args(why="the honest reason", stance="offering"))
    assert res["why"] == "the honest reason"
    assert res["stance"] == "offering"
    assert res["content"] == _args()["content"]


@pytest.mark.parametrize("blank", ["why", "stance", "trigger"])
def test_mark_share_rejects_blank_grammar(l_store, blank):
    tool = build_mark_share_tool(lattice_store=l_store, owner_agent="aetheria")
    with pytest.raises(ValueError, match=blank):
        tool.handler(_args(**{blank: "  "}))


def test_mark_share_has_no_async_delivery_fields(l_store):
    # Live surface: schema must NOT carry the async-only delivery fields.
    tool = build_mark_share_tool(lattice_store=l_store, owner_agent="aetheria")
    props = tool.schema["properties"]
    for f in ("urgency", "context_hint", "thread_id", "new_thread_title"):
        assert f not in props
    assert set(tool.schema["required"]) == {"content", "why", "stance", "trigger"}
