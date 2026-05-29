"""Tests for the provenance-aware lattice writer."""

from __future__ import annotations

from soveryn.platform.lattice import AtticStore, LatticeStore, Region
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass
from soveryn.platform.lattice.writer import LatticeWriter, WriteResult, write


def _provenance() -> Provenance:
    return Provenance(
        ProvenanceClass.WITNESSED,
        source="session:test",
        confidence=0.95,
        temporal_context="now",
        generator="test",
    )


def test_auto_write_lands_in_canonical_lattice_with_provenance(tmp_path):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    writer = LatticeWriter(lattice_store=lattice, attic_store=attic, agent="aetheria")

    result = writer.write(
        "session opened",
        region=Region.EPISODIC,
        kind="session_boundary",
        provenance=_provenance(),
    )

    assert result.destination == "lattice"
    assert result.lattice_id
    assert result.attic_id is None
    node = lattice.get_node(result.lattice_id)
    assert node.content == "session opened"
    assert node.type == "episodic"
    assert node.provenance["cls"] == "witnessed"
    assert node.provenance["confirmed"] is False
    assert attic.fetch("session opened") == ()


def test_unconfirmed_confirm_class_write_routes_to_attic_not_canonical(tmp_path):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    writer = LatticeWriter(lattice_store=lattice, attic_store=attic, agent="aetheria")

    result = writer.write(
        "Jon is upset with me",
        region=Region.AFFECTIVE,
        kind="emotional_label",
        provenance=_provenance(),
        confirmed=False,
    )

    assert result.destination == "attic"
    assert result.lattice_id is None
    assert result.attic_id
    assert lattice.find_nodes_by_keywords("aetheria", "upset") == ()
    entries = attic.fetch("upset")
    assert [entry.id for entry in entries] == [result.attic_id]
    assert entries[0].metadata["pending_confirmation"] is True
    assert entries[0].metadata["intended_region"] == "affective"
    assert entries[0].metadata["write_kind"] == "emotional_label"
    assert entries[0].provenance == _provenance()


def test_confirmed_confirm_class_write_lands_canonical_with_confirmation_recorded(tmp_path):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")

    result = write(
        "Aetheria identity statement",
        region=Region.IDENTITY,
        kind="identity_shift",
        provenance=_provenance(),
        confirmed=True,
        lattice_store=lattice,
        attic_store=attic,
        agent="aetheria",
    )

    assert isinstance(result, WriteResult)
    assert result.destination == "lattice"
    assert result.attic_id is None
    node = lattice.get_node(result.lattice_id)
    assert node.type == "identity"
    assert node.provenance["confirmed"] is True
    assert node.provenance["confirmation_required"] is True
    assert attic.fetch("identity") == ()


def test_interpretive_unconfirmed_semantic_write_cannot_become_canonical(tmp_path):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")

    result = write(
        "Jon will probably prefer this forever",
        region=Region.SEMANTIC,
        kind="prediction",
        provenance=_provenance(),
        confirmed=False,
        lattice_store=lattice,
        attic_store=attic,
        agent="aetheria",
    )

    assert result.destination == "attic"
    assert lattice.find_nodes_by_keywords("aetheria", "forever") == ()
    assert len(attic.fetch("forever")) == 1
