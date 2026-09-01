"""Process-local embedding scan cache — Eve 2026-09-01 Part A remainder.

The float32 blob path already scores with numpy per query. The remaining
cost is rebuilding that matrix on every recall. Cache it keyed by corpus
version; a write must show up on the next search.
"""
from __future__ import annotations

import math

from soveryn.platform.lattice.legacy import (
    LAYER_PRIVATE,
    LatticeStore,
    _SCAN_CACHE,
    _scan_cache_key,
)


def _vec(seed: int, dim: int = 64) -> tuple[float, ...]:
    return tuple(math.sin(seed * 0.7 + i * 0.013) for i in range(dim))


def _seed(store: LatticeStore, n: int = 40) -> list[str]:
    ids = []
    for i in range(n):
        ids.append(store.write_node(
            "aetheria", f"memory number {i}", node_type="fact",
            embedding=_vec(i),
            provenance={"cls": "witnessed", "source": "test",
                        "confidence": 0.9, "temporal_context": "t",
                        "generator": "test"},
        ))
    return ids


def test_second_search_reuses_cache_and_matches(tmp_path):
    store = LatticeStore(tmp_path / "lattice.db")
    _seed(store)
    query = _vec(7)
    first = store.find_nodes_by_embedding("aetheria", query, limit=10, threshold=0.0)
    key = _scan_cache_key(store.db_path)
    assert key in _SCAN_CACHE
    version = _SCAN_CACHE[key].version
    second = store.find_nodes_by_embedding("aetheria", query, limit=10, threshold=0.0)
    assert _SCAN_CACHE[key].version == version
    assert [n.id for n, _ in first] == [n.id for n, _ in second]
    for (_, a), (_, b) in zip(first, second):
        assert abs(a - b) < 1e-5


def test_write_is_visible_on_next_search(tmp_path):
    store = LatticeStore(tmp_path / "lattice.db")
    _seed(store, 8)
    query = _vec(99)
    before = {n.id for n, _ in store.find_nodes_by_embedding(
        "aetheria", query, limit=20, threshold=-1.0
    )}
    new_id = store.write_node(
        "aetheria", "brand new", node_type="fact", embedding=_vec(99),
    )
    after = store.find_nodes_by_embedding(
        "aetheria", query, limit=20, threshold=-1.0
    )
    assert new_id not in before
    assert after[0][0].id == new_id


def test_other_agents_private_stays_hidden(tmp_path):
    store = LatticeStore(tmp_path / "lattice.db")
    hidden = store.write_node(
        "eve", "eve secret", node_type="fact",
        layer=LAYER_PRIVATE, embedding=_vec(1),
    )
    visible = store.write_node(
        "aetheria", "aetheria note", node_type="fact",
        embedding=_vec(1),
    )
    hits = store.find_nodes_by_embedding(
        "aetheria", _vec(1), limit=10, threshold=-1.0
    )
    ids = {n.id for n, _ in hits}
    assert visible in ids
    assert hidden not in ids


def test_cached_path_matches_uncached_ranking(tmp_path):
    store = LatticeStore(tmp_path / "lattice.db")
    _seed(store, 30)
    query = _vec(11)
    cached = store.find_nodes_by_embedding("aetheria", query, limit=10, threshold=0.0)
    _SCAN_CACHE.clear()
    again = store.find_nodes_by_embedding("aetheria", query, limit=10, threshold=0.0)
    assert [n.id for n, _ in cached] == [n.id for n, _ in again]
