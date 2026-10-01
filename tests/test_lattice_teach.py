"""Lattice teach loop S1–S4 unit tests."""

from __future__ import annotations

import sqlite3

from soveryn.platform.lattice import AtticStore, LatticeStore
from soveryn.platform.lattice.fact_rail import CANONICAL_FACT_TAG
from soveryn.platform.lattice.legacy import LAYER_GLOBAL
from soveryn.platform.lattice.teach import (
    HISTORICAL_SNAPSHOT_TAG,
    build_remember_fact_tool,
    entity_tag,
    find_current_canonical_by_entity,
    remember_fact,
)


def _stores(tmp_path):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    return lattice, attic


def test_remember_fact_writes_global_canonical(tmp_path):
    lattice, attic = _stores(tmp_path)
    out = remember_fact(
        "CWG phone is (910) 581-3970",
        entity="cwg.phone",
        source="jon",
        as_of="2026-09-06",
        lattice_store=lattice,
        attic_store=attic,
        agent="aetheria",
    )
    assert out["ok"] is True
    assert out["lattice_id"]
    assert out.get("superseded_id") is None
    node = lattice.get_node(out["lattice_id"])
    assert node is not None
    assert node.layer == LAYER_GLOBAL
    assert node.type == "fact"
    assert CANONICAL_FACT_TAG in node.tags
    assert entity_tag("cwg.phone") in node.tags
    assert node.provenance["cls"] == "told"
    assert node.provenance["source"] == "jon"
    assert node.provenance["generator"] == "teach_loop"
    assert node.provenance["receipt"]["kind"] == "user_remember"
    assert attic.fetch("910") == ()


def test_remember_fact_supersedes_entity(tmp_path):
    lattice, attic = _stores(tmp_path)
    first = remember_fact(
        "Dan Ward rebuild active",
        entity="cwg.job.dan_ward",
        lattice_store=lattice,
        attic_store=attic,
        agent="eve",
    )
    second = remember_fact(
        "Dan Ward rebuild ON HOLD — do not quote dollars",
        entity="cwg.job.dan_ward",
        lattice_store=lattice,
        attic_store=attic,
        agent="eve",
    )
    assert first["ok"] and second["ok"]
    assert second["superseded_id"] == first["lattice_id"]
    assert second["lattice_id"] != first["lattice_id"]

    old = lattice.get_node(first["lattice_id"])
    new = lattice.get_node(second["lattice_id"])
    assert HISTORICAL_SNAPSHOT_TAG in old.tags
    assert old.content == "Dan Ward rebuild active"
    assert CANONICAL_FACT_TAG in new.tags
    assert HISTORICAL_SNAPSHOT_TAG not in new.tags
    assert new.layer == LAYER_GLOBAL

    current = find_current_canonical_by_entity(lattice, "cwg.job.dan_ward")
    assert current is not None
    assert current.id == second["lattice_id"]

    with sqlite3.connect(str(lattice.db_path)) as con:
        edge = con.execute(
            "SELECT relationship FROM edges WHERE source_id=? AND target_id=?",
            (second["lattice_id"], first["lattice_id"]),
        ).fetchone()
        assert edge is not None
        assert edge[0] == "supersedes"
        log = con.execute(
            "SELECT old_id, new_id, run_id FROM representation_log WHERE old_id=?",
            (first["lattice_id"],),
        ).fetchone()
        assert log is not None
        assert log[1] == second["lattice_id"]
        assert str(log[2]).startswith("teach:")


def test_fact_rail_returns_seed(tmp_path):
    lattice, attic = _stores(tmp_path)
    out = remember_fact(
        "CWG has no public street address; service-area + (910) 581-3970 only",
        entity="house.rule.no_street_address",
        lattice_store=lattice,
        attic_store=attic,
        agent="aetheria",
    )
    hits = lattice.find_canonical_facts("eve", "what is the 910 number")
    assert any(n.id == out["lattice_id"] for n in hits)
    hits_a = lattice.find_canonical_facts("aetheria", "street address 910")
    assert any(n.id == out["lattice_id"] for n in hits_a)


def test_historical_excluded_by_default(tmp_path):
    lattice, attic = _stores(tmp_path)
    first = remember_fact(
        "TTS was F5",
        entity="lab.voice.tts",
        lattice_store=lattice,
        attic_store=attic,
        agent="aetheria",
    )
    second = remember_fact(
        "Aetheria TTS = Kokoro (not F5)",
        entity="lab.voice.tts",
        lattice_store=lattice,
        attic_store=attic,
        agent="aetheria",
    )
    rail = lattice.find_canonical_facts("aetheria", "TTS Kokoro F5")
    ids = {n.id for n in rail}
    assert second["lattice_id"] in ids
    assert first["lattice_id"] not in ids
    assert find_current_canonical_by_entity(lattice, "lab.voice.tts").id == second["lattice_id"]


def test_remember_fact_idempotent_same_content(tmp_path):
    lattice, attic = _stores(tmp_path)
    a = remember_fact(
        "same claim",
        entity="house.test.same",
        lattice_store=lattice,
        attic_store=attic,
        agent="aetheria",
    )
    b = remember_fact(
        "same claim",
        entity="house.test.same",
        lattice_store=lattice,
        attic_store=attic,
        agent="aetheria",
    )
    assert a["lattice_id"] == b["lattice_id"]
    assert b.get("unchanged") is True


def test_build_remember_fact_tool_handler(tmp_path):
    lattice, attic = _stores(tmp_path)
    tool = build_remember_fact_tool(lattice, attic, "aetheria")
    assert tool.name == "remember_fact"
    assert tool.owner == "aetheria"
    result = tool.handler(
        {"content": "Kernel = OpenCode + Sparks", "entity": "lab.kernel.runtime"}
    )
    assert result["ok"] is True
    node = lattice.get_node(result["lattice_id"])
    assert node.layer == "global"
    assert "canonical_fact" in node.tags
