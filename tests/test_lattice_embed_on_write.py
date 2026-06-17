"""Embed-on-write: coordination (create_node) and library nodes are embedded
at write time when an embed_fn is wired, so they're recallable by every
agent's semantic recall — closing the 2026-06-17 FCC recurrence path. Opt-in
+ best-effort: no embed_fn → unembedded (test-safe, no HTTP); embed failure
never blocks the write.
"""
from __future__ import annotations
import sqlite3

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.coordination.store import CoordinationStore
from soveryn.platform.coordination.types import CoordBoard


def _fake_embed(text):
    return (0.1, 0.2, 0.3)


def _embedding(db, node_id):
    with sqlite3.connect(str(db)) as con:
        row = con.execute("SELECT embedding FROM nodes WHERE id=?", (node_id,)).fetchone()
    return row[0] if row else None


def test_coord_create_node_embeds_when_embed_fn_given(tmp_path):
    db = tmp_path / "l.db"; LatticeStore(db)
    store = CoordinationStore(db, embed_fn=_fake_embed)
    n = store.create_node(board=CoordBoard.BLUEPRINT, owner="vett", content="FCC blueprint")
    assert _embedding(db, n.id) is not None, "coord node should be embedded on write"


def test_coord_create_node_unembedded_without_embed_fn(tmp_path):
    db = tmp_path / "l.db"; LatticeStore(db)
    store = CoordinationStore(db)  # no embed_fn → no embedding, no HTTP (test-safe)
    n = store.create_node(board=CoordBoard.BLUEPRINT, owner="vett", content="FCC blueprint")
    assert _embedding(db, n.id) is None


def test_coord_embed_is_best_effort(tmp_path):
    db = tmp_path / "l.db"; LatticeStore(db)

    def boom(text):
        raise RuntimeError("embedder down")

    store = CoordinationStore(db, embed_fn=boom)
    n = store.create_node(board=CoordBoard.BLUEPRINT, owner="vett", content="resilient write")
    assert n.id  # write succeeded despite embed failure
    assert _embedding(db, n.id) is None  # embedding skipped, not fatal


def test_library_write_embeds_when_embed_fn_given(tmp_path):
    from soveryn.platform.library.tools import build_write_library_node_tool
    db = tmp_path / "l.db"; store = LatticeStore(db)
    tool = build_write_library_node_tool(
        lattice_store=store, owner_agent="vett", embed_fn=_fake_embed,
    )
    res = tool.handler({"content": "FCC library fact for recall"})
    assert _embedding(db, res["id"]) is not None, "library node should be embedded on write"
