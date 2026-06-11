"""Lattice tool handlers — read-through, no writes.

Verifies the SOVERYN-side lattice tool handler contract used by the
vendored harness. Uses fakes (not the real LatticeStore) so the contract
is testable in isolation; integration with the real LatticeStore is
exercised in Task 12's smoke test.
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from soveryn.agents.vett.harness.lattice_tools import (
    LatticeToolHandlers,
    format_search_observation,
)


class _FakeNode:
    """Mirrors the real soveryn.platform.lattice.Node dataclass surface used here.

    Only `.id` and `.content` are touched by the handlers — see
    docs/notes/2026-06-11-lattice-discovery.md.
    """

    def __init__(self, node_id: str, content: str) -> None:
        self.id = node_id
        self.content = content


class _FakeLattice:
    """Minimal fake exposing the real LatticeStore methods we call."""

    def __init__(self, nodes: Iterable[_FakeNode]) -> None:
        self._nodes = list(nodes)

    def find_nodes_by_embedding(
        self,
        agent: str,
        embedding,
        *,
        limit: int,
        threshold: float = 0.0,
        layer_filter: Optional[str] = None,
    ):
        # Real return shape: tuple of (Node, score). Score is a float.
        return tuple(
            (n, 1.0 - i * 0.1) for i, n in enumerate(self._nodes[:limit])
        )

    def get_node(self, node_id: str):
        for n in self._nodes:
            if n.id == node_id:
                return n
        return None


def _fake_embed(text: str) -> Tuple[float, ...]:
    # 768-dim, matches nomic-embed-text-v1.5
    return tuple([0.0] * 768)


def test_search_corpus_returns_formatted_observation():
    """search_corpus runs embed → find_nodes_by_embedding → format."""
    fake = _FakeLattice(
        [
            _FakeNode("n-1", "Alpha is the first letter."),
            _FakeNode("n-2", "Beta is the second letter."),
        ]
    )
    h = LatticeToolHandlers(lattice=fake, embed_fn=_fake_embed, agent_name="vett")
    result = h.search_corpus(query="what is alpha", top_k=2)
    assert "# DOCUMENT ID: n-1" in result
    assert "Alpha is the first letter." in result
    assert "# DOCUMENT ID: n-2" in result


def test_search_corpus_passes_agent_name_to_lattice():
    """Handler forwards `agent_name` (defaults to 'vett') to find_nodes_by_embedding."""
    captured = {}

    class _SpyLattice:
        def find_nodes_by_embedding(
            self, agent, embedding, *, limit, threshold=0.0, layer_filter=None
        ):
            captured["agent"] = agent
            captured["limit"] = limit
            captured["layer_filter"] = layer_filter
            return ()

        def get_node(self, node_id):
            return None

    h = LatticeToolHandlers(lattice=_SpyLattice(), embed_fn=_fake_embed, agent_name="vett")
    h.search_corpus(query="anything", top_k=3)
    assert captured["agent"] == "vett"
    assert captured["limit"] == 3


def test_fan_out_search_dispatches_to_multiple_queries():
    """fan_out_search calls search_corpus for each query and concatenates."""
    fake = _FakeLattice(
        [_FakeNode("n-1", "Topic A"), _FakeNode("n-2", "Topic B")]
    )
    h = LatticeToolHandlers(lattice=fake, embed_fn=_fake_embed, agent_name="vett")
    result = h.fan_out_search(queries=["query1", "query2"], top_k_per_query=2)
    assert result.count("# DOCUMENT ID:") >= 2


def test_read_doc_returns_full_text_for_known_id():
    fake = _FakeLattice([_FakeNode("n-1", "This is the full text of node 1.")])
    h = LatticeToolHandlers(lattice=fake, embed_fn=_fake_embed, agent_name="vett")
    result = h.read_doc(doc_id="n-1")
    assert "This is the full text of node 1." in result


def test_read_doc_returns_not_found_for_missing_id():
    fake = _FakeLattice([])
    h = LatticeToolHandlers(lattice=fake, embed_fn=_fake_embed, agent_name="vett")
    result = h.read_doc(doc_id="nonexistent")
    assert "not found" in result.lower()


def test_format_observation_uses_harness_canonical_marker():
    """Format helper produces strings parseable by vendored parse_doc_ids_from_observation."""
    obs = format_search_observation(
        [("doc-1", "Text one."), ("doc-2", "Text two.")]
    )
    assert "# DOCUMENT ID: doc-1" in obs
    assert "# DOCUMENT ID: doc-2" in obs

    from soveryn.agents.vett.harness.vendor.ultra_core import (
        parse_doc_ids_from_observation,
    )

    parsed = parse_doc_ids_from_observation(obs)
    assert "doc-1" in parsed
    assert "doc-2" in parsed
