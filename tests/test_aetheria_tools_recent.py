import json

from soveryn.agents.aetheria.tools.recent import build_recent_tool
from soveryn.platform.lattice.legacy import LatticeStore


def _insert_node(
    store: LatticeStore,
    *,
    node_id: str,
    content: str,
    created_at: str,
    provenance_cls: str = "witnessed",
    agent: str = "aetheria",
) -> None:
    store.write_node(
        "aetheria",
        "schema bootstrap",
        provenance={
            "cls": "witnessed",
            "source": "bootstrap",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    with store._conn() as conn:
        conn.execute("DELETE FROM nodes WHERE content = ?", ("schema bootstrap",))
        conn.execute(
            "INSERT INTO nodes "
            "(id, type, layer, agent, content, intensity, salience, access_count, "
            "tags, created_at, updated_at, embedding, intent, provenance) "
            "VALUES (?, 'memory', 'private', ?, ?, 0.5, 0.5, 0, "
            "?, ?, ?, NULL, NULL, ?)",
            (
                node_id,
                agent,
                content,
                json.dumps([]),
                created_at,
                created_at,
                json.dumps(
                    {
                        "cls": provenance_cls,
                        "source": "legacy_lattice" if provenance_cls == "legacy" else "test",
                        "confidence": 0.9,
                        "temporal_context": "fixture",
                        "generator": "test",
                    }
                ),
            ),
        )


def test_recent_returns_most_recent_by_created_at_desc(tmp_path) -> None:
    store = LatticeStore(tmp_path / "lattice.db")
    _insert_node(store, node_id="old", content="old memory", created_at="2026-05-28T00:00:00Z")
    _insert_node(store, node_id="new", content="new memory", created_at="2026-05-30T00:00:00Z")

    result = build_recent_tool(store=store).handler({"limit": 2})

    assert [entry["id"] for entry in result["stateable"]] == ["new", "old"]


def test_recent_channel_classifies_and_does_not_leak_b_content(tmp_path) -> None:
    store = LatticeStore(tmp_path / "lattice.db")
    _insert_node(store, node_id="a1", content="recent witnessed", created_at="2026-05-30T00:00:00Z")
    _insert_node(
        store,
        node_id="b1",
        content="RECENT LEAK CANARY legacy",
        created_at="2026-05-29T00:00:00Z",
        provenance_cls="legacy",
    )

    result = build_recent_tool(store=store).handler({"limit": 10})

    assert [entry["id"] for entry in result["stateable"]] == ["a1"]
    assert result["uncertain_count_by_class"] == {"legacy": 1}
    # Channel B content is returned since 2026-08-03 — the guarantee is
    # that it never reaches `stateable`, not that it is absent entirely.
    assert "RECENT LEAK CANARY" not in repr(result["stateable"])


def test_recent_limit_caps_total_result_count(tmp_path) -> None:
    store = LatticeStore(tmp_path / "lattice.db")
    _insert_node(store, node_id="old", content="old memory", created_at="2026-05-28T00:00:00Z")
    _insert_node(store, node_id="new", content="new memory", created_at="2026-05-30T00:00:00Z")

    result = build_recent_tool(store=store).handler({"limit": 1})

    total = len(result["stateable"]) + sum(result["uncertain_count_by_class"].values())
    assert total == 1
    assert result["stateable"][0]["id"] == "new"


def test_recent_returns_the_owners_own_entries_not_aetherias(tmp_path) -> None:
    """The whole point of parameterising this one (2026-08-20).

    `recent_lattice_entries` called `iter_nodes(agent="aetheria")` literally.
    Registering it for another agent by flipping only `ToolSpec.owner` would
    have handed Kernel *Aetheria's* private memories and labelled them his.
    """
    store = LatticeStore(tmp_path / "lattice.db")
    _insert_node(
        store, node_id="a1", content="aetheria private thought",
        created_at="2026-08-19T00:00:00Z", agent="aetheria",
    )
    _insert_node(
        store, node_id="k1", content="kernel build note",
        created_at="2026-08-18T00:00:00Z", agent="kernel",
    )

    result = build_recent_tool(store=store, owner_agent="kernel").handler({"limit": 10})

    assert [entry["id"] for entry in result["stateable"]] == ["k1"]
    assert "aetheria private thought" not in repr(result)


def test_recent_is_owner_parameterised(tmp_path) -> None:
    store = LatticeStore(tmp_path / "lattice.db")

    spec = build_recent_tool(store=store, owner_agent="kernel")

    assert spec.owner == "kernel"
    assert spec.name == "recent_lattice_entries"


def test_recent_defaults_to_aetheria(tmp_path) -> None:
    store = LatticeStore(tmp_path / "lattice.db")

    assert build_recent_tool(store=store).owner == "aetheria"
