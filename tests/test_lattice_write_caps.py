"""write_node content caps (Memory Grades PR2)."""
from __future__ import annotations

import pytest

from soveryn.platform.lattice.content_caps import CONTENT_CAPS
from soveryn.platform.lattice.legacy import LatticeError, LatticeStore


@pytest.fixture()
def store(tmp_path):
    return LatticeStore(tmp_path / "lattice.db")


def test_write_node_clamps_when_daemon_policy(store):
    limit = CONTENT_CAPS["reflection"]
    long = "x" * (limit + 200)
    nid = store.write_node(
        "aetheria", long, node_type="reflection", on_overflow="clamp",
    )
    node = store.get_node(nid)
    assert node is not None
    assert len(node.content) == limit
    assert node.content.endswith("…")


def test_write_node_raises_by_default_on_overflow(store):
    limit = CONTENT_CAPS["fact"]
    with pytest.raises(LatticeError):
        store.write_node("aetheria", "y" * (limit + 1), node_type="fact")


def test_write_node_passthrough_under_cap(store):
    nid = store.write_node("aetheria", "short fact", node_type="fact")
    assert store.get_node(nid).content == "short fact"
