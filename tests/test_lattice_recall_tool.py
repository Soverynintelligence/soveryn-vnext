"""Self-initiated recall tool (memory_recall) unit tests.

Self-model roadmap item 2: the seat queries its own lattice mid-work.
Mirrors test_lattice_teach.py patterns: real LatticeStore in tmp_path,
fake embed_fn with deterministic vectors.
"""

from __future__ import annotations

import math

from soveryn.platform.lattice import LatticeStore
from soveryn.platform.lattice.recall_tool import build_memory_recall_tool


DIM = 8


def _fake_embed(text: str, prompt: str = "document") -> tuple[float, ...]:
    """Deterministic keyword-ish vectors so cosine scoring is predictable."""
    v = [0.0] * DIM
    for i, ch in enumerate(text.lower()):
        v[i % DIM] += ord(ch) % 7
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / norm for x in v)


def _store(tmp_path) -> LatticeStore:
    return LatticeStore(tmp_path / "lattice.db")


def _write(lattice: LatticeStore, agent: str, text: str) -> None:
    lattice.write_node(
        agent=agent,
        content=text,
        node_type="fact",
        layer="global",
        embedding=_fake_embed(text),
        provenance={
            "cls": "told",
            "source": "jon",
            "confidence": 1.0,
            "temporal_context": "2026-10-04T00:00:00-04:00",
            "generator": "test",
        },
    )


def _tool(lattice):
    return build_memory_recall_tool(lattice, "aetheria", embed_fn=_fake_embed)


def test_returns_hits_for_matching_query(tmp_path):
    lattice = _store(tmp_path)
    _write(lattice, "aetheria", "Kernel brain is GLM-5.3-Flash at 10.10.10.2:8001")
    _write(lattice, "aetheria", "Completely unrelated note about tulips and rain")

    out = _tool(lattice).handler({"query": "Kernel brain endpoint"})
    assert out["ok"] is True
    assert out["n_hits"] >= 1
    assert "GLM-5.3-Flash" in out["recall"]


def test_missing_query_is_arg_error(tmp_path):
    out = _tool(_store(tmp_path)).handler({})
    assert out["ok"] is False
    assert "query" in out["error"]


def test_no_hits_is_ok_with_empty_recall(tmp_path):
    out = _tool(_store(tmp_path)).handler({"query": "anything"})
    assert out["ok"] is True
    assert out["n_hits"] == 0


def test_k_clamped_and_respected(tmp_path):
    lattice = _store(tmp_path)
    for i in range(12):
        _write(lattice, "aetheria", f"note number {i} about pond maintenance")
    out = _tool(lattice).handler({"query": "pond maintenance", "k": 99})
    assert out["ok"] is True
    assert out["n_hits"] <= 20


def test_historical_snapshot_excluded_by_default(tmp_path):
    lattice = _store(tmp_path)
    lattice.write_node(
        agent="aetheria",
        content="old archived chronicle of the april migration",
        node_type="fact",
        layer="global",
        embedding=_fake_embed("old archived chronicle of the april migration"),
        tags=("historical_snapshot",),
    )
    query = {"query": "april migration chronicle"}
    out = _tool(lattice).handler(dict(query))
    assert out["n_hits"] == 0
    out = _tool(lattice).handler({**query, "include_historical": True})
    assert out["n_hits"] >= 1


def test_other_agents_private_nodes_not_leaked(tmp_path):
    lattice = _store(tmp_path)
    lattice.write_node(
        agent="eve",
        content="eve private reflection about her family",
        node_type="reflection",
        layer="private",
        embedding=_fake_embed("eve private reflection about her family"),
    )
    out = _tool(lattice).handler({"query": "eve private reflection family"})
    assert out["n_hits"] == 0
