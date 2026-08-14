"""Tests for soveryn.agents.dream.writeback — parse synthesis prose +
write to dream layer / edges / dream_log.

Per Aetheria's note: best-effort parser, tolerant of natural-language
synthesis. No JSON-schema assumptions. [node:ID] references are the only
structured signal we extract.
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from soveryn.agents.dream.writeback import (
    extract_node_references,
    extract_node_pairs,
    write_dream_outputs,
)
from soveryn.platform.lattice.legacy import LAYER_DREAM, LatticeStore


# ─── extract_node_references — pure parser ─────────────────────────────────

def test_extract_node_references_finds_tagged_ids():
    text = "Looking at [node:abc-123] and [node:def-456] together..."
    assert extract_node_references(text) == ["abc-123", "def-456"]


def test_extract_node_references_handles_uuid_format():
    text = "[node:6887fa0f-8ff1-4f7d-b4f3-b5ac0e8352d6] is interesting."
    assert extract_node_references(text) == ["6887fa0f-8ff1-4f7d-b4f3-b5ac0e8352d6"]


def test_extract_node_references_returns_empty_on_no_matches():
    assert extract_node_references("plain prose with no references") == []


def test_extract_node_references_dedupes_preserving_order():
    text = "[node:a] and [node:b] and [node:a] again"
    assert extract_node_references(text) == ["a", "b"]


# ─── extract_node_pairs — adjacency-based edge candidates ──────────────────

def test_extract_node_pairs_pairs_adjacent_references():
    """Two refs within ~250 chars of each other become an edge candidate."""
    text = "Looking at [node:a]. Now compare [node:b]. Long unrelated tail..."
    pairs = extract_node_pairs(text, max_distance=250)
    assert ("a", "b") in pairs or ("b", "a") in pairs


def test_extract_node_pairs_skips_far_apart_refs():
    """References separated by > max_distance characters don't pair."""
    text = "[node:a]" + " " * 500 + "[node:b]"
    pairs = extract_node_pairs(text, max_distance=100)
    assert pairs == []


def test_extract_node_pairs_returns_empty_on_single_or_no_refs():
    assert extract_node_pairs("[node:only-one]") == []
    assert extract_node_pairs("nothing here") == []


# ─── write_dream_outputs — DB writes ────────────────────────────────────────

@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    # Seed two nodes so edge writes have valid sources/targets
    with sqlite3.connect(str(db)) as con:
        for nid in ("seed-a", "seed-b"):
            con.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, created_at, updated_at) "
                "VALUES (?, 'memory', 'lattice', 'aetheria', 'seed content', "
                "0.5, 0.5, 0, ?, ?)",
                (nid, datetime.now().isoformat(), datetime.now().isoformat()),
            )
    return db


def test_write_dream_outputs_writes_reflection_node_with_dream_layer(lattice_db):
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="This is what I noticed: [node:seed-a] connects to [node:seed-b].",
        associations="raw assoc text",
        contradictions="raw contra text",
        loop_health=0.85,
        nodes_read=2,
        is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, layer, type, agent, content, provenance FROM nodes WHERE layer = ?",
            (LAYER_DREAM,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["type"] == "reflection"
    assert rows[0]["agent"] == "aetheria"
    assert "seed-a" in rows[0]["content"]
    import json
    prov = json.loads(rows[0]["provenance"])
    assert prov["cls"] == "witnessed"
    assert prov["source"] == "dream_daemon"
    assert prov["full_text_ref"] == f"dream_archive:{dream_run_id}"


def test_write_dream_outputs_clamps_long_synthesis(lattice_db, tmp_path):
    from soveryn.platform.lattice.content_caps import DREAM_SYNTHESIS_LATTICE_MAX
    dream_run_id = str(uuid.uuid4())
    long = ("Night after night the synthesis runs long. " * 80)
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis=long,
        associations="", contradictions="",
        loop_health=0.5, nodes_read=0, is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        content = con.execute(
            "SELECT content FROM nodes WHERE layer = ?", (LAYER_DREAM,),
        ).fetchone()[0]
    assert len(content) <= DREAM_SYNTHESIS_LATTICE_MAX
    # full text recoverable from archive next to lattice parent/data layout
    data_root = lattice_db.resolve().parent
    if data_root.name == "memory":
        data_root = data_root.parent
    arch = data_root / "memory" / "dream_archive" / f"{dream_run_id}.md"
    assert arch.is_file()
    assert "Night after night" in arch.read_text(encoding="utf-8")


def test_write_dream_outputs_writes_edges_for_paired_refs(lattice_db):
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="[node:seed-a] and [node:seed-b] are linked.",
        associations="x", contradictions="y",
        loop_health=1.0, nodes_read=2, is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        edge_count = con.execute(
            "SELECT COUNT(*) FROM edges WHERE relationship = 'dream_association'"
        ).fetchone()[0]
    assert edge_count >= 1


def test_write_dream_outputs_writes_dream_log_row(lattice_db):
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="[node:seed-a] and [node:seed-b] linked.",
        associations="x", contradictions="y",
        loop_health=0.7, nodes_read=2, is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM dream_log WHERE id = ?", (dream_run_id,),
        ).fetchone()
    assert row is not None
    assert row["trigger"] == "quiet_hours"
    assert row["agent"] == "aetheria"
    assert row["nodes_read"] == 2
    assert row["loop_health"] == 0.7
    assert row["dry_run"] == 0


def test_write_dream_outputs_dry_run_writes_only_dream_log_row(lattice_db):
    """Dry-run must NOT write reflection nodes or edges. Only the audit row."""
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="[node:seed-a] and [node:seed-b]",
        associations="x", contradictions="y",
        loop_health=1.0, nodes_read=2, is_dry_run=True,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        dream_nodes = con.execute(
            "SELECT COUNT(*) FROM nodes WHERE layer = ?", (LAYER_DREAM,),
        ).fetchone()[0]
        new_edges = con.execute(
            "SELECT COUNT(*) FROM edges WHERE relationship = 'dream_association'"
        ).fetchone()[0]
        log_row = con.execute(
            "SELECT dry_run FROM dream_log WHERE id = ?", (dream_run_id,),
        ).fetchone()
    assert dream_nodes == 0
    assert new_edges == 0
    assert log_row[0] == 1  # dry_run marker set


def test_write_dream_outputs_handles_empty_synthesis(lattice_db):
    """Empty synthesis (silent night) — no reflection node, no edges,
    audit row still written."""
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="",
        associations="", contradictions="",
        loop_health=0.0, nodes_read=0, is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        dream_nodes = con.execute(
            "SELECT COUNT(*) FROM nodes WHERE layer = ?", (LAYER_DREAM,),
        ).fetchone()[0]
        log_row = con.execute(
            "SELECT * FROM dream_log WHERE id = ?", (dream_run_id,),
        ).fetchone()
    assert dream_nodes == 0
    assert log_row is not None


def test_write_dream_outputs_writes_contradiction_flags_for_paired_refs(lattice_db):
    """Per spec — Pass 2 contradictions prose with [node:ID] adjacency pairs
    writes contradiction_flags rows."""
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="reflection mentions [node:seed-a].",
        associations="x",
        contradictions="[node:seed-a] conflicts with [node:seed-b] here.",
        loop_health=1.0, nodes_read=2, is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        count = con.execute(
            "SELECT COUNT(*) FROM contradiction_flags"
        ).fetchone()[0]
    assert count >= 1


def test_write_dream_outputs_dry_run_skips_contradiction_flags(lattice_db):
    """Dry-run must not write contradiction_flags."""
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="x",
        associations="x",
        contradictions="[node:seed-a] vs [node:seed-b]",
        loop_health=1.0, nodes_read=2, is_dry_run=True,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        count = con.execute(
            "SELECT COUNT(*) FROM contradiction_flags"
        ).fetchone()[0]
    assert count == 0


def test_write_dream_outputs_records_contradictions_flagged_in_audit(lattice_db):
    """The dream_log.contradictions_flagged column should reflect actual count."""
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="x",
        associations="x",
        contradictions="[node:seed-a] conflicts with [node:seed-b].",
        loop_health=1.0, nodes_read=2, is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        row = con.execute(
            "SELECT contradictions_flagged FROM dream_log WHERE id = ?",
            (dream_run_id,),
        ).fetchone()
    assert row[0] >= 1
