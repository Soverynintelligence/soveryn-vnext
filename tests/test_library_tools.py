"""Tests for the library layer tool factories.

Library is shared cross-agent reference material — layer='library' on the
existing lattice nodes table. Writes are passive (no coord webhook events).
All three agents have read+write access; attribution survives via the agent
column.
"""

from __future__ import annotations

import pytest

from soveryn.platform.lattice.legacy import (
    LAYER_LIBRARY,
    LatticeStore,
)
from soveryn.platform.library import (
    build_search_library_tool,
    build_write_library_node_tool,
    register_library_tools,
)
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


@pytest.fixture
def lattice_store(tmp_path):
    return LatticeStore(tmp_path / "test_lattice.db")


def _fake_embed(text: str) -> tuple[float, ...]:
    """Deterministic stub embedding — never hits the live embed server."""
    # Length + char-sum encoding gives different vectors for different inputs
    # without needing a real model.
    return tuple(float(c) / 256 for c in text.encode("utf-8")[:768])


# ─── write_library_node ─────────────────────────────────────────────────────

def test_write_library_node_creates_node_with_layer_library(lattice_store):
    tool = build_write_library_node_tool(
        lattice_store=lattice_store, owner_agent="aetheria",
    )
    result = tool.handler({"content": "verified fact about EU funding"})
    assert "id" in result
    assert result["layer"] == LAYER_LIBRARY
    assert result["written_by"] == "aetheria"
    # Confirm DB persistence
    import sqlite3
    with sqlite3.connect(str(lattice_store.db_path)) as con:
        row = con.execute(
            "SELECT layer, agent, type, content FROM nodes WHERE id = ?",
            (result["id"],),
        ).fetchone()
    assert row[0] == LAYER_LIBRARY
    assert row[1] == "aetheria"
    assert row[2] == "library"
    assert row[3] == "verified fact about EU funding"


def test_write_library_node_records_attribution(lattice_store):
    """Multiple agents writing produces nodes attributed to each."""
    for agent in ("aetheria", "vett", "scotty"):
        tool = build_write_library_node_tool(
            lattice_store=lattice_store, owner_agent=agent,
        )
        tool.handler({"content": f"library entry written by {agent}"})
    import sqlite3
    with sqlite3.connect(str(lattice_store.db_path)) as con:
        rows = con.execute(
            "SELECT agent FROM nodes WHERE layer = ? ORDER BY agent",
            (LAYER_LIBRARY,),
        ).fetchall()
    assert [r[0] for r in rows] == ["aetheria", "scotty", "vett"]


def test_write_library_node_accepts_tags(lattice_store):
    tool = build_write_library_node_tool(
        lattice_store=lattice_store, owner_agent="vett",
    )
    result = tool.handler({
        "content": "Horizon Europe deadline: Q3 2026",
        "tags": ["funding", "eu", "horizon-europe"],
    })
    import sqlite3, json
    with sqlite3.connect(str(lattice_store.db_path)) as con:
        row = con.execute("SELECT tags FROM nodes WHERE id = ?",
                          (result["id"],)).fetchone()
    tags = json.loads(row[0])
    assert tags == ["funding", "eu", "horizon-europe"]


def test_write_library_node_rejects_empty_content(lattice_store):
    tool = build_write_library_node_tool(
        lattice_store=lattice_store, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="non-empty"):
        tool.handler({"content": "   "})


def test_write_library_node_rejects_non_string_tags(lattice_store):
    tool = build_write_library_node_tool(
        lattice_store=lattice_store, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="strings"):
        tool.handler({"content": "fact", "tags": [1, 2, 3]})


def test_write_library_node_returns_content_head_for_truncation(lattice_store):
    tool = build_write_library_node_tool(
        lattice_store=lattice_store, owner_agent="aetheria",
    )
    long_content = "x" * 1000
    result = tool.handler({"content": long_content})
    # Full content persists; head is for the response payload only
    assert len(result["content_head"]) == 200


# ─── search_library ─────────────────────────────────────────────────────────

def test_search_library_returns_results_for_library_nodes(lattice_store):
    # Seed three library nodes with embeddings (write via the tool so the
    # embed_fn path is exercised end-to-end).
    write_tool = build_write_library_node_tool(
        lattice_store=lattice_store, owner_agent="vett",
    )
    write_tool.handler({"content": "EU sovereign AI funding window Q3 2026"})
    write_tool.handler({"content": "Mistral released MoE model under Apache 2.0"})
    write_tool.handler({"content": "Blackwell B200 supports NVFP4 natively"})
    # Library write doesn't compute embeddings, so for search we need to
    # manually backfill embeddings on these rows. Use the same _fake_embed.
    import sqlite3, json
    with sqlite3.connect(str(lattice_store.db_path)) as con:
        rows = con.execute("SELECT id, content FROM nodes "
                            "WHERE layer = ?", (LAYER_LIBRARY,)).fetchall()
        for nid, content in rows:
            emb = _fake_embed(content)
            con.execute("UPDATE nodes SET embedding = ? WHERE id = ?",
                         (json.dumps(list(emb)), nid))

    search_tool = build_search_library_tool(
        lattice_store=lattice_store, embed_fn=_fake_embed, owner_agent="aetheria",
    )
    # Query something embedding-close to the EU funding entry.
    result = search_tool.handler({"query": "EU sovereign AI funding window Q3 2026"})
    assert result["count"] >= 1
    contents = [r["content"] for r in result["results"]]
    assert any("EU sovereign AI funding" in c for c in contents)
    # Each result includes attribution
    assert all("written_by" in r for r in result["results"])


def test_search_library_rejects_invalid_k(lattice_store):
    tool = build_search_library_tool(
        lattice_store=lattice_store, embed_fn=_fake_embed, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="positive integer"):
        tool.handler({"query": "anything", "k": 0})
    with pytest.raises(ToolArgError, match="positive integer"):
        tool.handler({"query": "anything", "k": -5})


def test_search_library_rejects_excessive_k(lattice_store):
    tool = build_search_library_tool(
        lattice_store=lattice_store, embed_fn=_fake_embed, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="<= "):
        tool.handler({"query": "anything", "k": 1000})


def test_search_library_rejects_empty_query(lattice_store):
    tool = build_search_library_tool(
        lattice_store=lattice_store, embed_fn=_fake_embed, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="non-empty"):
        tool.handler({"query": ""})


# ─── register_library_tools ─────────────────────────────────────────────────

def test_register_library_tools_registers_both(lattice_store):
    registry = ToolRegistry()
    register_library_tools(
        registry,
        lattice_store=lattice_store,
        embed_fn=_fake_embed,
        owner_agent="aetheria",
    )
    aetheria_tools = {t.name for t in registry.iter_tools_for_agent("aetheria")}
    assert "write_library_node" in aetheria_tools
    assert "search_library" in aetheria_tools


def test_register_library_tools_per_agent_isolation(lattice_store):
    """Each agent gets its own owner-keyed copy of the tools. No leakage
    across owners (the registry's standard behaviour)."""
    registry = ToolRegistry()
    for agent in ("aetheria", "vett", "scotty"):
        register_library_tools(
            registry,
            lattice_store=lattice_store,
            embed_fn=_fake_embed,
            owner_agent=agent,
        )
    for agent in ("aetheria", "vett", "scotty"):
        tools = {t.name for t in registry.iter_tools_for_agent(agent)}
        assert "write_library_node" in tools
        assert "search_library" in tools
