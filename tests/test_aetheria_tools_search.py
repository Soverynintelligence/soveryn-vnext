import pytest

from soveryn.agents.aetheria.tools.search import (
    build_search_by_embedding_tool,
    build_search_by_keywords_tool,
)
from soveryn.platform.lattice.legacy import LatticeStore


@pytest.fixture
def store(tmp_path) -> LatticeStore:
    lattice = LatticeStore(tmp_path / "lattice.db")
    lattice.write_node(
        "aetheria",
        "canonical witnessed memory",
        node_type="memory",
        intensity=0.8,
        embedding=(0.1, 0.2, 0.3),
        provenance={
            "cls": "witnessed",
            "source": "test",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    lattice.write_node(
        "aetheria",
        "LEAK CANARY raw legacy memory",
        node_type="memory",
        intensity=0.7,
        embedding=(0.1, 0.2, 0.3),
        provenance={
            "cls": "legacy",
            "source": "legacy_lattice",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    return lattice


def test_search_returns_channel_split(store: LatticeStore) -> None:
    spec = build_search_by_embedding_tool(
        store=store,
        embed_fn=lambda text: (0.1, 0.2, 0.3),
    )

    result = spec.handler({"query": "any", "k": 5})

    assert len(result["stateable"]) == 1
    assert result["stateable"][0]["rendered"] == "I remember canonical witnessed memory"
    assert result["uncertain_count_by_class"].get("legacy") == 1
    # Channel B content is returned since 2026-08-03 — the guarantee is
    # that it never reaches `stateable`, not that it is absent entirely.
    assert "LEAK CANARY" not in repr(result["stateable"])


def test_search_threshold_param_filters(store: LatticeStore) -> None:
    spec = build_search_by_embedding_tool(
        store=store,
        embed_fn=lambda text: (0.1, 0.2, 0.3),
    )

    result = spec.handler({"query": "any", "k": 5, "threshold": 0.99})

    total = len(result["stateable"]) + sum(result["uncertain_count_by_class"].values())
    assert total >= 1


def test_search_k_param_caps_results(store: LatticeStore) -> None:
    spec = build_search_by_embedding_tool(
        store=store,
        embed_fn=lambda text: (0.1, 0.2, 0.3),
    )

    result = spec.handler({"query": "any", "k": 1})

    total = len(result["stateable"]) + sum(result["uncertain_count_by_class"].values())
    assert total == 1


def test_search_schema_requires_query(store: LatticeStore) -> None:
    spec = build_search_by_embedding_tool(store=store, embed_fn=lambda text: (0.0,))

    assert spec.name == "search_lattice_by_embedding"
    assert spec.owner == "aetheria"
    schema = spec.schema
    assert schema["type"] == "object"
    assert "query" in schema["properties"]
    assert "query" in schema["required"]
    assert schema["properties"]["k"]["default"] == 5
    assert schema["properties"]["threshold"]["default"] == 0.70


def test_keyword_search_returns_channel_split(store: LatticeStore) -> None:
    spec = build_search_by_keywords_tool(store=store)

    result = spec.handler({"keywords": ["memory"], "k": 5})

    assert len(result["stateable"]) == 1
    assert result["stateable"][0]["rendered"] == "I remember canonical witnessed memory"
    assert result["uncertain_count_by_class"].get("legacy") == 1
    # Channel B content is returned since 2026-08-03 — the guarantee is
    # that it never reaches `stateable`, not that it is absent entirely.
    assert "LEAK CANARY" not in repr(result["stateable"])


def test_keyword_search_k_param_caps_results(store: LatticeStore) -> None:
    spec = build_search_by_keywords_tool(store=store)

    result = spec.handler({"keywords": ["memory"], "k": 1})

    total = len(result["stateable"]) + sum(result["uncertain_count_by_class"].values())
    assert total == 1


def test_keyword_search_schema_requires_keywords_array(store: LatticeStore) -> None:
    spec = build_search_by_keywords_tool(store=store)

    assert spec.name == "search_lattice_by_keywords"
    assert spec.owner == "aetheria"
    schema = spec.schema
    assert schema["type"] == "object"
    assert schema["properties"]["keywords"]["type"] == "array"
    assert schema["properties"]["keywords"]["items"] == {"type": "string"}
    assert "keywords" in schema["required"]
    assert schema["properties"]["k"]["default"] == 5


@pytest.fixture
def distinct_keyword_store(tmp_path) -> LatticeStore:
    """Three nodes with distinct content words for UNION testing.
    Each node is matched by a unique keyword."""
    lattice = LatticeStore(tmp_path / "lattice_union.db")
    provenance = {
        "cls": "witnessed",
        "source": "test",
        "confidence": 0.9,
        "temporal_context": "fixture",
        "generator": "test",
    }
    lattice.write_node(
        "aetheria", "apple harvest in october",
        node_type="memory", intensity=0.8,
        embedding=(0.1, 0.2, 0.3), provenance=provenance,
    )
    lattice.write_node(
        "aetheria", "banana ripening time",
        node_type="memory", intensity=0.8,
        embedding=(0.1, 0.2, 0.3), provenance=provenance,
    )
    lattice.write_node(
        "aetheria", "cherry blossom season",
        node_type="memory", intensity=0.8,
        embedding=(0.1, 0.2, 0.3), provenance=provenance,
    )
    return lattice


def test_keyword_search_union_two_distinct_keywords_match_two_distinct_nodes(
    distinct_keyword_store: LatticeStore,
) -> None:
    """UNION semantics: when multiple keywords match different nodes, ALL
    matching nodes surface in the result — not just the first keyword's
    hits. This is the documented design call from Track 2 Task 6: the
    per-keyword loop in the handler accumulates union'd results deduped
    by node id."""
    spec = build_search_by_keywords_tool(store=distinct_keyword_store)

    result = spec.handler({"keywords": ["apple", "banana"], "k": 5})

    # Channel A entries: both apple and banana nodes are canonical witnessed,
    # so both go to stateable. Cherry is not in either keyword → not in result.
    rendered = [entry["rendered"] for entry in result["stateable"]]
    assert any("apple harvest" in r for r in rendered), \
        f"apple node missing from UNION: {rendered}"
    assert any("banana ripening" in r for r in rendered), \
        f"banana node missing from UNION: {rendered}"
    assert not any("cherry blossom" in r for r in rendered), \
        f"cherry node leaked into UNION result: {rendered}"


def test_keyword_search_union_dedupes_node_when_multiple_keywords_match_it(
    distinct_keyword_store: LatticeStore,
) -> None:
    """If both keywords match the SAME node (the apple harvest node contains
    both 'apple' and 'harvest'), the node surfaces exactly once — dedup by
    node id, not double-counted."""
    spec = build_search_by_keywords_tool(store=distinct_keyword_store)

    result = spec.handler({"keywords": ["apple", "harvest"], "k": 5})

    rendered = [entry["rendered"] for entry in result["stateable"]]
    apple_matches = [r for r in rendered if "apple harvest" in r]
    assert len(apple_matches) == 1, \
        f"apple harvest node should appear exactly once via dedup, got: {rendered}"


def test_keyword_search_union_respects_k_cap_across_keywords(
    distinct_keyword_store: LatticeStore,
) -> None:
    """When k=1 and two keywords each match a distinct node, only one node
    surfaces — k caps the TOTAL across the union, not per-keyword."""
    spec = build_search_by_keywords_tool(store=distinct_keyword_store)

    result = spec.handler({"keywords": ["apple", "banana"], "k": 1})

    total = len(result["stateable"]) + sum(result["uncertain_count_by_class"].values())
    assert total == 1, f"k=1 should cap union to one node, got total={total}"
