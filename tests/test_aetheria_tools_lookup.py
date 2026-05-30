import pytest

from soveryn.agents.aetheria.tools.lookup import build_get_node_tool
from soveryn.platform.lattice.legacy import LatticeStore


@pytest.fixture
def node_ids(tmp_path) -> tuple[LatticeStore, str, str]:
    store = LatticeStore(tmp_path / "lattice.db")
    channel_a_id = store.write_node(
        "aetheria",
        "single witnessed memory",
        node_type="memory",
        provenance={
            "cls": "witnessed",
            "source": "test",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    channel_b_id = store.write_node(
        "aetheria",
        "LOOKUP LEAK CANARY legacy memory",
        node_type="memory",
        provenance={
            "cls": "legacy",
            "source": "legacy_lattice",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    return store, channel_a_id, channel_b_id


def test_get_node_returns_channel_a_rendered_entry(node_ids) -> None:
    store, channel_a_id, _channel_b_id = node_ids
    spec = build_get_node_tool(store=store)

    result = spec.handler({"node_id": channel_a_id})

    assert result["stateable"] == [
        {
            "id": channel_a_id,
            "provenance_class": "witnessed",
            "source": "test",
            "rendered": "I remember single witnessed memory",
        }
    ]
    assert result["uncertain_count_by_class"] == {}


def test_get_node_returns_channel_b_count_only(node_ids) -> None:
    store, _channel_a_id, channel_b_id = node_ids
    spec = build_get_node_tool(store=store)

    result = spec.handler({"node_id": channel_b_id})

    assert result["stateable"] == []
    assert result["uncertain_count_by_class"] == {"legacy": 1}
    assert "LOOKUP LEAK CANARY" not in repr(result)


def test_get_node_not_found_returns_flag(node_ids) -> None:
    store, _channel_a_id, _channel_b_id = node_ids
    spec = build_get_node_tool(store=store)

    result = spec.handler({"node_id": "missing-node"})

    assert result == {
        "stateable": [],
        "uncertain_count_by_class": {},
        "not_found": True,
    }


def test_get_node_schema_requires_node_id(node_ids) -> None:
    store, _channel_a_id, _channel_b_id = node_ids
    spec = build_get_node_tool(store=store)

    assert spec.name == "get_lattice_node"
    assert spec.owner == "aetheria"
    schema = spec.schema
    assert schema["type"] == "object"
    assert schema["properties"]["node_id"]["type"] == "string"
    assert "node_id" in schema["required"]
