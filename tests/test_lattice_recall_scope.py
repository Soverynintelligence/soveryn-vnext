"""Recall visibility scope: every agent recalls its OWN nodes + every OTHER
agent's nodes EXCEPT their private; dream layer excluded for everyone.

Regression for the 2026-06-17 FCC miss: Aetheria's recall could not see Vett's
coordination/library nodes (other-agent, non-global) — they were excluded by
the old `(own non-global) OR (anyone's global)` filter, and library was
excluded entirely. Jon's rule: "all agents see all nodes except those private
to the agent themselves."
"""
from __future__ import annotations
import json
import sqlite3

from soveryn.platform.lattice.legacy import (
    LatticeStore, LAYER_PRIVATE, LAYER_LIBRARY,
)


def _raw_node(store, *, node_id, agent, layer, node_type="fact", emb=(1.0, 0.0)):
    """Insert a node directly (for layers write_node won't accept, e.g. the
    coordination 'lattice' layer and 'dream'). Mirrors write_node's columns."""
    with sqlite3.connect(str(store.db_path)) as con:
        con.execute(
            "INSERT INTO nodes (id,type,layer,agent,content,intensity,salience,"
            "access_count,tags,created_at,updated_at,embedding,intent,provenance) "
            "VALUES (?,?,?,?,?,?,?,0,?,?,?,?,?,?)",
            (node_id, node_type, layer, agent, f"{layer} node from {agent}",
             0.8, 0.8, "[]", "2026-06-17T00:00:00", "2026-06-17T00:00:00",
             json.dumps(list(emb)), None, None),
        )


def test_recall_cross_agent_visibility(tmp_path):
    store = LatticeStore(tmp_path / "l.db")
    emb = (1.0, 0.0)

    own_priv = store.write_node(agent="aetheria", content="own private",
                                layer=LAYER_PRIVATE, embedding=emb)
    vett_priv = store.write_node(agent="vett", content="vett private",
                                 layer=LAYER_PRIVATE, embedding=emb)
    vett_lib = store.write_node(agent="vett", content="vett library fact",
                                layer=LAYER_LIBRARY, embedding=emb)
    # Vett's coordination node — layer 'lattice' (how coord nodes actually store)
    _raw_node(store, node_id="vett-coord", agent="vett", layer="lattice",
              node_type="coordination", emb=emb)
    # dream layer (internal consolidation) — must never surface in recall
    _raw_node(store, node_id="own-dream", agent="aetheria", layer="dream", emb=emb)

    ids = {n.id for n, _ in store.find_nodes_by_embedding("aetheria", emb, threshold=0.5)}

    assert own_priv in ids, "own private should be recallable"
    assert vett_lib in ids, "another agent's library should now be recallable"
    assert "vett-coord" in ids, "another agent's coordination (non-private) should be recallable"
    assert vett_priv not in ids, "another agent's PRIVATE must stay hidden"
    assert "own-dream" not in ids, "dream layer must be excluded from recall"
