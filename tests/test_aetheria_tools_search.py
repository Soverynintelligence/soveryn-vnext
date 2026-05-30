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
    assert "LEAK CANARY" not in repr(result)


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
    assert "LEAK CANARY" not in repr(result)


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
