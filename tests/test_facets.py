"""Tests for provisional lattice facets as metadata labels."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from soveryn.platform.lattice import Entry, Region
from soveryn.platform.lattice.attic import _SCHEMA_SQL as ATTIC_SCHEMA_SQL
from soveryn.platform.lattice.facets import (
    FACET_METADATA_KEY,
    PROVISIONAL_FACETS,
    add_facet,
    get_facets,
    remove_facet,
    replace_facet,
)
from soveryn.platform.lattice.legacy import _SCHEMA_SQL as LATTICE_SCHEMA_SQL


def test_provisional_facets_are_exact_metadata_labels():
    assert PROVISIONAL_FACETS == frozenset({
        "working_context",
        "pattern_reservoir",
        "friction_log",
        "salience_cache",
    })


def test_facets_are_represented_in_entry_metadata_not_schema_fields():
    entry = Entry(id="entry-1", content="x", region=Region.EPISODIC)

    updated = add_facet(entry, "working_context")

    assert updated is not entry
    assert updated.region is Region.EPISODIC
    assert updated.metadata[FACET_METADATA_KEY] == ["working_context"]
    assert get_facets(updated) == ("working_context",)
    assert not hasattr(updated, "facet")
    assert not hasattr(updated, "facets")
    with pytest.raises(FrozenInstanceError):
        updated.region = Region.SEMANTIC


def test_facets_can_be_renamed_removed_without_schema_migration():
    entry = Entry(id="entry-1", content="x", region=Region.SEMANTIC)
    entry = add_facet(entry, "pattern_reservoir")
    renamed = replace_facet(entry, "pattern_reservoir", "candidate_pattern")
    removed = remove_facet(renamed, "candidate_pattern")

    assert get_facets(renamed) == ("candidate_pattern",)
    assert get_facets(removed) == ()
    assert FACET_METADATA_KEY in removed.metadata


def test_facets_are_orthogonal_to_region():
    semantic = add_facet(Entry(id="s", content="x", region=Region.SEMANTIC), "friction_log")
    procedural = add_facet(Entry(id="p", content="x", region=Region.PROCEDURAL), "friction_log")

    assert semantic.region is Region.SEMANTIC
    assert procedural.region is Region.PROCEDURAL
    assert get_facets(semantic) == get_facets(procedural) == ("friction_log",)


def test_facet_labels_are_not_lattice_or_attic_schema_columns():
    schema = (LATTICE_SCHEMA_SQL + ATTIC_SCHEMA_SQL).lower()

    assert FACET_METADATA_KEY not in schema
    for facet in PROVISIONAL_FACETS:
        assert facet not in schema
