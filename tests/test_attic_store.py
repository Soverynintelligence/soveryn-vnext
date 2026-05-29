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


def test_promote_creates_canonical_lattice_entry_with_chain_and_preserves_raw(tmp_path):
    attic = AtticStore(tmp_path / "attic.db")
    lattice = LatticeStore(tmp_path / "lattice.db")
    raw = attic.append(
        "reviewed pattern",
        metadata={"facet": "pattern_reservoir"},
        linked_lattice_ids=("prior-lattice-id",),
    )
    before = attic.get_record(raw.id)

    promoted_id = attic.promote(
        raw.id,
        lattice_store=lattice,
        to_region=Region.SEMANTIC,
        trigger="review",
        agent="aetheria",
    )

    promoted = lattice.get_node(promoted_id)
    after = attic.get_record(raw.id)
    assert promoted is not None
    assert promoted.content == "reviewed pattern"
    assert promoted.type == "semantic"
    assert promoted.provenance["cls"] == "consolidated"
    assert promoted.provenance["source"] == "attic_promotion"
    assert promoted.provenance["chain"] == [raw.id]
    assert promoted.provenance["trigger"] == "review"
    assert after == before
    assert attic.fetch("reviewed")[0].id == raw.id


def test_promote_requires_valid_trigger(tmp_path):
    attic = AtticStore(tmp_path / "attic.db")
    lattice = LatticeStore(tmp_path / "lattice.db")
    raw = attic.append("unreviewed raw material")

    for trigger in (None, "", "volume", "recency"):
        try:
            attic.promote(raw.id, lattice_store=lattice, to_region=Region.SEMANTIC, trigger=trigger)
        except ValueError as exc:
            assert "trigger" in str(exc)
        else:
            raise AssertionError(f"trigger {trigger!r} should not promote")

    assert lattice.find_nodes_by_keywords("aetheria", "unreviewed") == ()


def test_corroboration_promotion_requires_threshold(tmp_path):
    attic = AtticStore(tmp_path / "attic.db")
    lattice = LatticeStore(tmp_path / "lattice.db")
    raw = attic.append("corroborated raw material")

    try:
        attic.promote(
            raw.id,
            lattice_store=lattice,
            to_region=Region.PROCEDURAL,
            trigger="corroboration",
            corroboration_count=1,
            corroboration_threshold=2,
        )
    except ValueError as exc:
        assert "corroboration" in str(exc)
    else:
        raise AssertionError("corroboration below threshold should not promote")

    promoted_id = attic.promote(
        raw.id,
        lattice_store=lattice,
        to_region=Region.PROCEDURAL,
        trigger="corroboration",
        corroboration_count=2,
        corroboration_threshold=2,
    )

    promoted = lattice.get_node(promoted_id)
    assert promoted.type == "procedural"
    assert promoted.provenance["trigger"] == "corroboration"
    assert promoted.provenance["corroboration_count"] == 2
    assert promoted.provenance["corroboration_threshold"] == 2


def test_volume_and_recency_never_auto_promote(tmp_path):
    attic = AtticStore(tmp_path / "attic.db")
    lattice = LatticeStore(tmp_path / "lattice.db")

    for _ in range(5):
        attic.append("repeated raw material")

    assert len(attic.fetch("repeated")) == 5
    assert lattice.find_nodes_by_keywords("aetheria", "repeated") == ()
