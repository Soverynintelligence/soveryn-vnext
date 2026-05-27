"""Tests for the platform lattice interface boundary."""

import pytest

from soveryn.platform.lattice import (
    AtticStore,
    Entry,
    LAYER_GLOBAL,
    LAYER_PRIVATE,
    LatticeStore,
    LegacyLatticeAdapter,
    Region,
    entry_from_node,
)


def test_entry_is_evidence_not_prompt_wording():
    entry = Entry(
        id="n1",
        content="Jon prefers Signal over Telegram.",
        region=Region.SEMANTIC,
        source="legacy_lattice",
        metadata={"layer": "global"},
    )

    assert entry.content == "Jon prefers Signal over Telegram."
    assert entry.region is Region.SEMANTIC
    assert "Recalled from memory" not in entry.content
    assert "I can" not in entry.content
    assert "write" not in entry.metadata


def test_legacy_adapter_returns_read_only_entries(tmp_path):
    store = LatticeStore(tmp_path / "lattice.db")
    store.write_node(
        "aetheria",
        "Signal is the outbound channel.",
        layer=LAYER_GLOBAL,
        node_type="fact",
        tags=("runtime",),
    )
    adapter = LegacyLatticeAdapter(store)

    entries = adapter.fetch("Signal", agent="aetheria")

    assert len(entries) == 1
    assert entries[0].content == "Signal is the outbound channel."
    assert entries[0].region is Region.SEMANTIC
    assert entries[0].source == "legacy_lattice"
    assert entries[0].metadata["layer"] == LAYER_GLOBAL
    assert not hasattr(adapter, "write_node")
    assert not hasattr(adapter, "append")


def test_private_legacy_node_marks_entry_private(tmp_path):
    store = LatticeStore(tmp_path / "lattice.db")
    node_id = store.write_node(
        "aetheria",
        "private observation",
        layer=LAYER_PRIVATE,
        node_type="event",
    )

    entry = entry_from_node(store.get_node(node_id))

    assert entry.private is True
    assert entry.region is Region.EPISODIC


def test_attic_store_interface_declared_not_implemented():
    attic = AtticStore()

    with pytest.raises(NotImplementedError):
        attic.fetch("private thought")


def test_memory_lattice_compatibility_shim_reexports_platform_objects():
    from soveryn.memory import lattice as compat
    from soveryn.platform import lattice as platform

    assert compat.LatticeStore is platform.LatticeStore
    assert compat.Node is platform.Node
    assert compat.LatticeError is platform.LatticeError
    assert compat.LegacyLatticeAdapter is platform.LegacyLatticeAdapter
