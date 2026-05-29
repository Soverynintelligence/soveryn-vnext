"""Tests for durable Attic storage."""

from __future__ import annotations

from soveryn.platform.lattice import AtticStore, LatticeStore, Region
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass


def test_attic_append_persists_record_with_default_raw_provenance(tmp_path):
    store = AtticStore(tmp_path / "attic.db")

    record = store.append(
        "uncertain cross-session pattern",
        metadata={"facet": "pattern_reservoir"},
        linked_lattice_ids=("lat-1",),
    )

    assert record.id
    assert record.content == "uncertain cross-session pattern"
    assert record.metadata == {"facet": "pattern_reservoir"}
    assert record.linked_lattice_ids == ("lat-1",)
    assert record.provenance.cls is ProvenanceClass.TOLD
    assert record.provenance.confidence < 0.5
    assert record.provenance.source == "attic"


def test_attic_fetch_returns_private_noncanonical_entries_and_filters_links(tmp_path):
    store = AtticStore(tmp_path / "attic.db")
    first = store.append("needs review before truth", linked_lattice_ids=("lat-1",))
    store.append("different raw note", linked_lattice_ids=("lat-2",))

    entries = store.fetch("review", include_links_to="lat-1")

    assert len(entries) == 1
    assert entries[0].id == first.id
    assert entries[0].content == "needs review before truth"
    assert entries[0].source == "attic"
    assert entries[0].region is Region.UNKNOWN
    assert entries[0].private is True
    assert entries[0].metadata["canonical"] is False
    assert entries[0].metadata["zone"] == "attic"
    assert entries[0].metadata["linked_lattice_ids"] == ["lat-1"]
    assert entries[0].provenance.cls is ProvenanceClass.TOLD


def test_attic_round_trips_across_store_reinstantiation(tmp_path):
    db_path = tmp_path / "attic.db"
    provenance = Provenance(
        ProvenanceClass.TOLD,
        source="jon",
        confidence=0.7,
        temporal_context="session-1",
        generator="test",
    )
    record = AtticStore(db_path).append("private but useful", provenance=provenance)

    entries = AtticStore(db_path).fetch("useful")

    assert [entry.id for entry in entries] == [record.id]
    assert entries[0].provenance == provenance


def test_attic_storage_is_separate_from_lattice_region_queries(tmp_path):
    attic = AtticStore(tmp_path / "attic.db")
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic.append("secret attic pattern", linked_lattice_ids=("lat-1",))
    lattice.write_node("aetheria", "public lattice pattern", node_type="fact")

    attic_entries = attic.fetch("pattern")
    lattice_nodes = lattice.find_nodes_by_keywords("aetheria", "pattern")

    assert [entry.content for entry in attic_entries] == ["secret attic pattern"]
    assert [node.content for node in lattice_nodes] == ["public lattice pattern"]
    assert all(node.content != "secret attic pattern" for node in lattice_nodes)
