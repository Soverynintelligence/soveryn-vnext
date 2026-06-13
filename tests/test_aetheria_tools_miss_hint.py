"""Aetheria search tools ↔ miss_hint integration.

Verifies that empty search results carry the layer-aware miss hint, and
that non-empty results don't (no audit noise on the happy path).
"""
from __future__ import annotations

import pytest

from soveryn.agents.aetheria.tools.search import (
    build_search_by_embedding_tool,
    build_search_by_keywords_tool,
)
from soveryn.platform.lattice.legacy import (
    LAYER_GLOBAL,
    LAYER_LIBRARY,
    LAYER_PRIVATE,
    LatticeStore,
)


@pytest.fixture
def store(tmp_path):
    return LatticeStore(tmp_path / "miss_hint_int.db")


def _fake_embed(_text: str) -> tuple[float, ...]:
    """Deterministic embedding so tests don't depend on a live model."""
    return (1.0, 0.0, 0.0)


# ─── Embedding-tool: empty result gets a miss hint ──────────────────────────

def test_embedding_search_attaches_miss_hint_when_empty(store):
    """No matching node exists. The hint must surface the layer where
    the query tokens DO show up."""
    # Seed: a global-layer node that matches the query lexically (so the
    # miss hint catches it) but its embedding won't match the fake query
    # vector — the embedding search returns empty.
    store.write_node(
        "aetheria", "the scotty rename memo from tinker 2026 05 02",
        node_type="fact", layer=LAYER_GLOBAL,
        embedding=(0.0, 1.0, 0.0),  # orthogonal to _fake_embed
    )
    tool = build_search_by_embedding_tool(store=store, embed_fn=_fake_embed)
    result = tool.handler({"query": "scotty rename memo 2026 tinker"})
    assert result["stateable"] == []
    assert result["uncertain_count_by_class"] == {}
    assert "miss_hint" in result
    hint = result["miss_hint"]
    assert hint["layer_counts"][LAYER_GLOBAL] == 1
    # The hint must include the probed tokens so debugging is auditable
    assert "scotty" in hint["tokens_probed"]


def test_embedding_search_does_not_attach_miss_hint_on_hit(store):
    """When the search actually finds something, no miss hint — clean
    happy-path response stays clean."""
    store.write_node(
        "aetheria", "matched content",
        node_type="fact", layer=LAYER_PRIVATE,
        embedding=(1.0, 0.0, 0.0),  # parallel to _fake_embed → matches
    )
    tool = build_search_by_embedding_tool(store=store, embed_fn=_fake_embed)
    result = tool.handler({"query": "anything"})
    assert "miss_hint" not in result


# ─── Keywords-tool: same shape ──────────────────────────────────────────────

def test_keyword_search_attaches_miss_hint_when_empty(store):
    """find_nodes_by_keywords scans private+global by default but
    excludes library. A library-only node won't be found by the keyword
    search — but the miss hint must surface it."""
    store.write_node(
        "aetheria", "the rare gizmotron lives in the library",
        node_type="fact", layer=LAYER_LIBRARY,
    )
    tool = build_search_by_keywords_tool(store=store)
    result = tool.handler({"keywords": ["gizmotron"]})
    assert result["stateable"] == []
    assert result["uncertain_count_by_class"] == {}
    assert "miss_hint" in result
    assert result["miss_hint"]["layer_counts"][LAYER_LIBRARY] == 1


def test_keyword_search_no_miss_hint_on_hit(store):
    """Match exists in the searched space → no hint."""
    store.write_node(
        "aetheria", "scotty was renamed",
        node_type="fact", layer=LAYER_PRIVATE,
    )
    tool = build_search_by_keywords_tool(store=store)
    result = tool.handler({"keywords": ["scotty"]})
    assert "miss_hint" not in result


# ─── Both tools: empty everywhere → all-zero hint ───────────────────────────

def test_miss_hint_with_no_matches_anywhere_returns_all_zero_counts(store):
    """Nothing in any layer matches → miss hint counts are all zero but
    still present. The agent learns 'there's literally nothing here'
    instead of 'maybe rephrase'."""
    tool = build_search_by_embedding_tool(store=store, embed_fn=_fake_embed)
    result = tool.handler({"query": "absolutely nonexistent term flunkbird"})
    assert "miss_hint" in result
    counts = result["miss_hint"]["layer_counts"]
    assert all(v == 0 for v in counts.values())
