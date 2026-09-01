from __future__ import annotations

import math

import pytest

pytest.importorskip("turbovec")

from soveryn.platform.kb.chunk import chunk_markdown
from soveryn.platform.kb.recall import recall
from soveryn.platform.kb.store import KBStore
from soveryn.platform.lattice.legacy import LatticeStore


def _vec(seed: int, dim: int = 32) -> tuple[float, ...]:
    return tuple(math.sin(seed * 0.7 + i * 0.013) for i in range(dim))


def test_add_sync_reload_round_trip(tmp_path):
    root = tmp_path / "kb"
    store = KBStore(root)
    store.add("docs/a.md#1", _vec(1), "pond liner 45 mil", source_path="docs/a.md")
    store.add("docs/b.md#1", _vec(9), "unrelated cooking notes", source_path="docs/b.md")
    store.sync()
    reloaded = KBStore(root)
    hits = reloaded.search(_vec(1), k=2)
    assert hits[0].chunk_id == "docs/a.md#1"
    assert "liner" in hits[0].content


def test_allowlist_restricts_hits(tmp_path):
    store = KBStore(tmp_path / "kb")
    store.add("a", _vec(1), "alpha")
    store.add("b", _vec(1), "beta")
    store.add("c", _vec(2), "gamma")
    hits = store.search(_vec(1), k=5, chunk_allowlist=["c"])
    assert [h.chunk_id for h in hits] == ["c"]


def test_recall_merges_lattice_and_kb(tmp_path):
    lattice = LatticeStore(tmp_path / "lattice.db")
    lattice.write_node(
        "aetheria", "Jon prefers surgical diffs",
        node_type="fact", embedding=_vec(3),
    )
    kb = KBStore(tmp_path / "kb")
    kb.add("docs/spec.md#1", _vec(8), "TurboQuant 4-bit reference index")

    def embed(text: str) -> tuple[float, ...]:
        if "surgical" in text:
            return _vec(3)
        return _vec(8)

    mem = recall(
        "surgical diffs", agent="aetheria", lattice=lattice, kb=kb,
        sources=["lattice", "kb"], embed_fn=embed, threshold=-1.0, limit=5,
    )
    assert mem[0].source == "legacy_lattice"
    ref = recall(
        "quantization", agent="aetheria", lattice=lattice, kb=kb,
        sources=["lattice", "kb"], embed_fn=embed, threshold=-1.0, limit=5,
    )
    assert any(e.source == "kb" for e in ref)


def test_recall_lattice_only_skips_kb(tmp_path):
    lattice = LatticeStore(tmp_path / "lattice.db")
    lattice.write_node("aetheria", "house memory", node_type="fact", embedding=_vec(1))
    kb = KBStore(tmp_path / "kb")
    kb.add("docs/x.md#1", _vec(1), "reference chunk")
    hits = recall(
        "q", agent="aetheria", lattice=lattice, kb=kb,
        sources=["lattice"], embed_fn=lambda _t: _vec(1),
        threshold=-1.0, limit=5,
    )
    assert hits
    assert all(e.source == "legacy_lattice" for e in hits)


def test_chunk_markdown_splits_headings():
    text = "# Title\n\nintro\n\n## One\n\nalpha\n\n## Two\n\nbeta"
    chunks = chunk_markdown(text, source_path="docs/x.md")
    ids = [c[0] for c in chunks]
    assert ids[0].startswith("docs/x.md#")
    assert any("alpha" in body for _, body in chunks)
    assert any("beta" in body for _, body in chunks)
