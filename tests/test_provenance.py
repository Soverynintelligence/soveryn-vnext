"""Tests for first-class lattice provenance."""

from __future__ import annotations

import pytest

from soveryn.platform.lattice import Entry, LatticeStore, Region, entry_from_node
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass


def test_provenance_class_values_are_exact():
    assert [item.value for item in ProvenanceClass] == [
        "witnessed",
        "told",
        "inferred",
        "consolidated",
        "legacy",
    ]


def test_provenance_carries_storage_epistemics():
    provenance = Provenance(
        ProvenanceClass.WITNESSED,
        source="session:abc",
        confidence=0.92,
        temporal_context="2026-05-29T09:15:00-04:00",
        generator="agent_loop",
        chain=("entry-1",),
    )

    assert provenance.cls is ProvenanceClass.WITNESSED
    assert provenance.source == "session:abc"
    assert provenance.confidence == 0.92
    assert provenance.temporal_context == "2026-05-29T09:15:00-04:00"
    assert provenance.generator == "agent_loop"
    assert provenance.chain == ("entry-1",)
    with pytest.raises(Exception):
        provenance.confidence = 0.5


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_provenance_confidence_must_be_in_unit_interval(confidence):
    with pytest.raises(ValueError, match="confidence"):
        Provenance(
            ProvenanceClass.TOLD,
            source="jon",
            confidence=confidence,
            temporal_context="now",
            generator="test",
        )


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_provenance_confidence_accepts_bounds(confidence):
    provenance = Provenance(
        ProvenanceClass.TOLD,
        source="jon",
        confidence=confidence,
        temporal_context="now",
        generator="test",
    )

    assert provenance.confidence == confidence


def test_inferred_provenance_requires_derivation_basis():
    with pytest.raises(ValueError, match="derived_from"):
        Provenance(
            ProvenanceClass.INFERRED,
            source="pattern_reservoir",
            confidence=0.4,
            temporal_context="cross-session",
            generator="memory_writer",
        )

    provenance = Provenance(
        ProvenanceClass.INFERRED,
        source="pattern_reservoir",
        confidence=0.4,
        temporal_context="cross-session",
        generator="memory_writer",
        derived_from=("entry-a", "entry-b"),
    )

    assert provenance.derived_from == ("entry-a", "entry-b")
    assert provenance.chain == ()


def test_provenance_accepts_string_class_and_normalizes_tuples():
    provenance = Provenance(
        "legacy",
        source="legacy_lattice",
        confidence=0.2,
        temporal_context="migration",
        generator="phase2b",
        chain=["old-id"],
    )

    assert provenance.cls is ProvenanceClass.LEGACY
    assert provenance.chain == ("old-id",)
    assert provenance.derived_from == ()


def test_entry_accepts_optional_structured_provenance():
    provenance = Provenance(
        ProvenanceClass.TOLD,
        source="jon",
        confidence=0.9,
        temporal_context="current-session",
        generator="test",
    )

    entry = Entry(
        id="entry-1",
        content="Jon prefers Signal.",
        region=Region.SEMANTIC,
        provenance=provenance,
    )

    assert entry.provenance is provenance


def test_entry_old_construction_defaults_provenance_none():
    entry = Entry(id="entry-1", content="Legacy shape still works.")

    assert entry.region is Region.UNKNOWN
    assert entry.source == "lattice"
    assert entry.provenance is None


def test_legacy_entry_from_node_keeps_metadata_provenance_but_no_structured_entry_provenance(tmp_path):
    store = LatticeStore(tmp_path / "lattice.db")
    node_id = store.write_node(
        "aetheria",
        "legacy memory",
        provenance={"source_type": "declared_fact"},
    )

    entry = entry_from_node(store.get_node(node_id))

    assert entry.source == "legacy_lattice"
    assert entry.metadata["provenance"] == {"source_type": "declared_fact"}
    assert entry.provenance is None
