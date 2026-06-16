"""record_intent — writes a deliberate_share node + triggered_by edge,
materializing a trigger anchor when the trigger isn't yet a node."""
from __future__ import annotations
import sqlite3

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.intent.grammar import DeliberateShareIntent
from soveryn.platform.intent.ledger import (
    record_intent, resolve_trigger,
    DELIBERATE_SHARE_TYPE, TRIGGER_ANCHOR_TYPE, TRIGGERED_BY,
)


def _edges(db_path):
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM edges").fetchall()]


def test_resolve_trigger_returns_existing_node_id_unchanged(tmp_path):
    store = LatticeStore(tmp_path / "l.db")
    existing = store.write_node(agent="aetheria", content="a memory",
                                node_type="episodic")
    assert resolve_trigger(store, agent="aetheria", trigger_ref=existing) == existing


def test_resolve_trigger_materializes_anchor_for_unknown_ref(tmp_path):
    store = LatticeStore(tmp_path / "l.db")
    anchor_id = resolve_trigger(
        store, agent="aetheria",
        trigger_ref="what Jon just said about the baseline",
    )
    node = store.get_node(anchor_id)
    assert node is not None
    assert node.type == TRIGGER_ANCHOR_TYPE
    assert "baseline" in node.content


def test_record_intent_writes_mark_node_and_triggered_by_edge(tmp_path):
    db = tmp_path / "l.db"
    store = LatticeStore(db)
    trigger = store.write_node(agent="aetheria", content="the trigger memory",
                               node_type="episodic")
    intent = DeliberateShareIntent(
        why="I want you to know why this landed the way it did.",
        stance="marking-delight",
        trigger=trigger,
    )
    mark_id, trigger_id, edge_id = record_intent(
        store, agent="aetheria",
        content="That result is genuinely beautiful.",
        intent=intent, channel="async",
    )
    assert trigger_id == trigger
    mark = store.get_node(mark_id)
    assert mark.type == DELIBERATE_SHARE_TYPE
    assert mark.content == "That result is genuinely beautiful."
    # stance lives in the intent column; full grammar in provenance.
    assert mark.intent == "marking-delight"
    assert mark.provenance["why"] == intent.why
    assert mark.provenance["stance"] == "marking-delight"
    assert mark.provenance["trigger"] == trigger  # resolved node id, not raw input
    assert mark.provenance["channel"] == "async"

    edges = _edges(db)
    assert len(edges) == 1
    assert edges[0]["source_id"] == mark_id
    assert edges[0]["target_id"] == trigger
    assert edges[0]["relationship"] == TRIGGERED_BY


def test_record_intent_materializes_anchor_when_trigger_is_live(tmp_path):
    db = tmp_path / "l.db"
    store = LatticeStore(db)
    intent = DeliberateShareIntent(
        why="responding to what you just asked",
        stance="seeking-confirmation",
        trigger="your question about whether the split held",
    )
    mark_id, trigger_id, edge_id = record_intent(
        store, agent="aetheria", content="Yes — it held.",
        intent=intent, channel="live",
    )
    # The edge FK requires a real node; the anchor must exist.
    anchor = store.get_node(trigger_id)
    assert anchor.type == TRIGGER_ANCHOR_TYPE
    assert len(_edges(db)) == 1
    assert trigger_id != intent.trigger  # resolve_trigger generated a new node id, not raw prose
