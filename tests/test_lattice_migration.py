from soveryn.platform.lattice.attic import AtticStore
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.lattice.migration import (
    LEGACY_MIGRATION_CONFIDENCE,
    LEGACY_MIGRATION_SOURCE,
    legacy_node_metadata,
    legacy_node_provenance,
    migrate_legacy_nodes_to_attic,
)
from soveryn.platform.lattice.provenance import ProvenanceClass


def test_legacy_node_metadata_preserves_old_fields(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    node_id = lattice.write_node(
        "aetheria",
        "legacy memory",
        node_type="fact",
        layer="private",
        intensity=0.7,
        tags=("identity", "memory"),
        intent="remember",
        provenance={"source_type": "old"},
    )
    node = lattice.get_node(node_id)

    metadata = legacy_node_metadata(node)

    assert metadata["legacy_id"] == node_id
    assert metadata["legacy_type"] == "fact"
    assert metadata["legacy_layer"] == "private"
    assert metadata["legacy_agent"] == "aetheria"
    assert metadata["legacy_intensity"] == 0.7
    assert metadata["legacy_salience"] == 0.7
    assert metadata["legacy_access_count"] == 0
    assert metadata["legacy_tags"] == ["identity", "memory"]
    assert metadata["legacy_intent"] == "remember"
    assert metadata["legacy_provenance"] == {"source_type": "old"}
    assert metadata["legacy_region_guess"] == "semantic"
    assert metadata["legacy_low_confidence"] is True


def test_legacy_node_provenance_is_low_confidence_legacy(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    node = lattice.get_node(lattice.write_node("aetheria", "legacy memory"))

    provenance = legacy_node_provenance(node, migrated_at="2026-05-30T00:00:00+00:00")

    assert provenance.cls is ProvenanceClass.LEGACY
    assert provenance.source == LEGACY_MIGRATION_SOURCE
    assert provenance.confidence == LEGACY_MIGRATION_CONFIDENCE
    assert provenance.temporal_context == "2026-05-30T00:00:00+00:00"
    assert provenance.generator == "legacy_to_attic_migration"
    assert provenance.chain == (node.id,)


def test_migrate_legacy_nodes_to_attic_copies_as_raw_noncanonical_entries(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    node_id = lattice.write_node("aetheria", "legacy memory", tags=("identity",))
    node = lattice.get_node(node_id)

    result = migrate_legacy_nodes_to_attic((node,), attic_store=attic)

    assert result.skipped_existing == ()
    assert len(result.migrated) == 1
    record = result.migrated[0]
    assert record.content == "legacy memory"
    assert record.linked_lattice_ids == (node_id,)
    assert record.provenance.cls is ProvenanceClass.LEGACY
    assert record.provenance.source == LEGACY_MIGRATION_SOURCE
    assert record.provenance.confidence == LEGACY_MIGRATION_CONFIDENCE
    assert record.metadata["legacy_id"] == node_id
    assert record.metadata["legacy_tags"] == ["identity"]

    fetched = attic.fetch("legacy")
    assert len(fetched) == 1
    assert fetched[0].metadata["canonical"] is False
    assert fetched[0].metadata["zone"] == "attic"
    assert fetched[0].metadata["linked_lattice_ids"] == [node_id]


def test_migrate_legacy_nodes_to_attic_is_idempotent_by_linked_lattice_id(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    node = lattice.get_node(lattice.write_node("aetheria", "legacy memory"))

    first = migrate_legacy_nodes_to_attic((node,), attic_store=attic)
    second = migrate_legacy_nodes_to_attic((node,), attic_store=attic)

    assert len(first.migrated) == 1
    assert second.migrated == ()
    assert second.skipped_existing == (node.id,)
    assert len(attic.records_linked_to(node.id)) == 1
