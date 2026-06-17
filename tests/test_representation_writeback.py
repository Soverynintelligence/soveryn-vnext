"""Tests for representation writeback: node write, edge resolution, supersede, dry_run.

Pattern mirrors tests/test_lattice_embed_on_write.py — set up via LatticeStore,
assert via direct sqlite3 queries.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.representation.parse import Conclusion
from soveryn.agents.representation.writeback import write_conclusions


def _fake_embed(text):
    return (0.1, 0.2, 0.3)


def _node_count(db):
    with sqlite3.connect(str(db)) as con:
        return con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]


def _edge_count(db):
    with sqlite3.connect(str(db)) as con:
        return con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]


def _log_count(db):
    with sqlite3.connect(str(db)) as con:
        return con.execute("SELECT COUNT(*) FROM representation_log").fetchone()[0]


def _get_node(db, node_id):
    with sqlite3.connect(str(db)) as con:
        con.row_factory = sqlite3.Row
        return con.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()


def _get_edges_by_rel(db, relationship):
    with sqlite3.connect(str(db)) as con:
        con.row_factory = sqlite3.Row
        return con.execute(
            "SELECT * FROM edges WHERE relationship=?", (relationship,)
        ).fetchall()


def _get_log_rows(db):
    with sqlite3.connect(str(db)) as con:
        con.row_factory = sqlite3.Row
        return con.execute("SELECT * FROM representation_log").fetchall()


# ─── Test 1: Live write — real premise node id gets an edge; synthetic turn: id does not ───

def test_live_write_real_premise_gets_edge(tmp_path):
    db = tmp_path / "l.db"
    store = LatticeStore(db)

    # Plant a real conclusion premise node so the edge resolves
    real_premise_id = store.write_node(
        agent="aetheria",
        content="Jon works through the night habitually",
        node_type="conclusion",
        layer="private",
    )

    # One conclusion referencing the real premise, one with a synthetic turn-id
    conclusions = [
        Conclusion(
            mode="inductive",
            confidence="fairly confident",
            content="Jon has a nocturnal work pattern",
            premises=(real_premise_id,),
        ),
        Conclusion(
            mode="abductive",
            confidence="tentative",
            content="Jon prefers direct communication",
            premises=("turn:sess123:0",),  # synthetic → no edge
        ),
    ]

    result = write_conclusions(
        store,
        conclusions,
        owner_agent="aetheria",
        subject="jon",
        run_id="run-test-1",
        embed_fn=_fake_embed,
        dry_run=False,
    )

    assert result["written"] == 2
    assert result["dry_run"] is False

    # Both nodes written
    assert _node_count(db) == 3  # 1 premise + 2 new conclusions

    # Verify the two NEW conclusion nodes: type, provenance contains confidence_rank
    # The premise node was also written as type='conclusion', so filter by provenance
    with sqlite3.connect(str(db)) as con:
        con.row_factory = sqlite3.Row
        # New nodes written by write_conclusions have provenance.kind='conclusion'
        all_rows = con.execute(
            "SELECT * FROM nodes WHERE type='conclusion' ORDER BY created_at"
        ).fetchall()
    # Filter to rows that have provenance.kind == 'conclusion' (written by writeback)
    new_rows = [r for r in all_rows if json.loads(r["provenance"] or "{}").get("kind") == "conclusion"]
    assert len(new_rows) == 2

    prov0 = json.loads(new_rows[0]["provenance"])
    assert prov0["confidence_rank"] == 2  # "fairly confident" → 2
    assert prov0["kind"] == "conclusion"
    assert prov0["subject"] == "jon"

    # Embedding stored for first conclusion (embed_fn was provided)
    emb0 = new_rows[0]["embedding"]
    assert emb0 is not None
    parsed_emb = json.loads(emb0)
    assert parsed_emb == [0.1, 0.2, 0.3]

    # Edge for real premise: concluded_from (new_conclusion → real_premise)
    edges = _get_edges_by_rel(db, "concluded_from")
    assert len(edges) == 1
    assert edges[0]["target_id"] == real_premise_id
    assert result["edges"] == 1

    prov1 = json.loads(new_rows[1]["provenance"])
    assert prov1["confidence_rank"] == 1  # "tentative" → 1


# ─── Test 2: Supersede — old node tagged, supersedes edge written, log row inserted ───

def test_supersede_loud_trail(tmp_path):
    db = tmp_path / "l.db"
    store = LatticeStore(db)

    # Plant the old conclusion node we're superseding
    old_id = store.write_node(
        agent="aetheria",
        content="Jon sleeps on a normal schedule",
        node_type="conclusion",
        layer="private",
    )

    # Plant a premise node so we can test the driving_premises JSON
    premise_id = store.write_node(
        agent="aetheria",
        content="Jon's chat logs show activity at 3am",
        node_type="conclusion",
        layer="private",
    )

    conclusions = [
        Conclusion(
            mode="inductive",
            confidence="confident",
            content="Jon is nocturnal — works consistently past midnight",
            premises=(premise_id, "turn:s:0"),
        ),
    ]

    result = write_conclusions(
        store,
        conclusions,
        owner_agent="aetheria",
        subject="jon",
        run_id="run-test-2",
        embed_fn=None,
        dry_run=False,
        supersedes={0: old_id},
    )

    assert result["superseded"] == 1

    # Old node must be tagged historical_snapshot
    old_node = _get_node(db, old_id)
    assert old_node is not None
    tags = json.loads(old_node["tags"])
    assert "historical_snapshot" in tags

    # supersedes edge: new → old
    supersedes_edges = _get_edges_by_rel(db, "supersedes")
    assert len(supersedes_edges) == 1
    assert supersedes_edges[0]["target_id"] == old_id

    # representation_log row
    log_rows = _get_log_rows(db)
    assert len(log_rows) == 1
    row = log_rows[0]
    assert row["old_id"] == old_id
    assert row["run_id"] == "run-test-2"
    assert row["confidence_to"] == "confident"

    driving = json.loads(row["driving_premises"])
    assert premise_id in driving
    assert "turn:s:0" in driving

    # new_content_head is the first 200 chars of new content
    assert row["new_content_head"].startswith("Jon is nocturnal")

    # old_content_head comes from old node's content
    assert row["old_content_head"] is not None
    assert "Jon sleeps" in row["old_content_head"]


# ─── Test 3: dry_run=True — nothing written ───

def test_dry_run_writes_nothing(tmp_path):
    db = tmp_path / "l.db"
    store = LatticeStore(db)

    conclusions = [
        Conclusion(
            mode="deductive",
            confidence="confident",
            content="This should not be persisted",
            premises=("turn:x:0",),
        ),
    ]

    result = write_conclusions(
        store,
        conclusions,
        owner_agent="aetheria",
        subject="jon",
        run_id="run-dry",
        embed_fn=_fake_embed,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert _node_count(db) == 0
    assert _edge_count(db) == 0
    assert _log_count(db) == 0
