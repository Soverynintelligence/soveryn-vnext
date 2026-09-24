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

    # Asserted field by field rather than by whole-dict equality. cd204c7
    # (2026-08-11) added `content` and `content_source` so a lookup returns the
    # body instead of a count — the fix for the false amnesia in e264382 — and
    # exact equality turned that correct addition into a failure. What matters
    # is that these fields are right, not that no others exist.
    (entry,) = result["stateable"]
    assert entry["id"] == channel_a_id
    assert entry["provenance_class"] == "witnessed"
    assert entry["source"] == "test"
    assert entry["rendered"] == "I remember single witnessed memory"
    assert entry["content"] == "single witnessed memory"
    assert entry["content_source"] == "lattice"
    assert result["uncertain_count_by_class"] == {}


def test_get_node_returns_channel_b_count_only(node_ids) -> None:
    store, _channel_a_id, channel_b_id = node_ids
    spec = build_get_node_tool(store=store)

    result = spec.handler({"node_id": channel_b_id})

    assert result["stateable"] == []
    assert result["uncertain_count_by_class"] == {"legacy": 1}
    # Channel B content is returned since 2026-08-03 — the guarantee is
    # that it never reaches `stateable`, not that it is absent entirely.
    assert "LOOKUP LEAK CANARY" not in repr(result["stateable"])


def test_get_node_not_found_returns_flag(node_ids) -> None:
    store, _channel_a_id, _channel_b_id = node_ids
    spec = build_get_node_tool(store=store)

    result = spec.handler({"node_id": "missing-node"})

    assert result["stateable"] == []
    assert result["uncertain_count_by_class"] == {}
    assert result["not_found"] is True
    # A miss must not smuggle content in through the Channel B lane either.
    assert result["context_only"] == []
    assert result["context_only_returned"] == 0
    assert result["context_only_omitted"] == 0


def test_get_node_schema_requires_node_id(node_ids) -> None:
    store, _channel_a_id, _channel_b_id = node_ids
    spec = build_get_node_tool(store=store)

    assert spec.name == "get_lattice_node"
    assert spec.owner == "aetheria"
    schema = spec.schema
    assert schema["type"] == "object"
    assert schema["properties"]["node_id"]["type"] == "string"
    assert "node_id" in schema["required"]


def test_get_node_is_owner_parameterised(node_ids) -> None:
    """Kernel/Vett/Scotty/Eve get the same deep read Aetheria has (2026-08-20).

    They already had the two search tools; without get_lattice_node a truncated
    search hit was a dead end for every agent but Aetheria — the same
    can't-see-my-own-memory shape as the 2026-08-02 Vett fix.
    """
    store, _channel_a_id, _channel_b_id = node_ids
    spec = build_get_node_tool(store=store, owner_agent="kernel")

    assert spec.owner == "kernel"
    assert spec.name == "get_lattice_node"


def test_get_node_reads_any_agents_node_by_id(node_ids) -> None:
    """Lookup is by id and stays id-addressed regardless of owner.

    Visibility is enforced upstream at search time; a node id the agent already
    holds resolves. Pinning this so a later "scope lookup to owner" change is a
    deliberate decision rather than a silent one.
    """
    store, channel_a_id, _channel_b_id = node_ids
    spec = build_get_node_tool(store=store, owner_agent="kernel")

    result = spec.handler({"node_id": channel_a_id})

    (entry,) = result["stateable"]
    assert entry["id"] == channel_a_id
