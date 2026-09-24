"""Embeddings move from JSON text to float32 binary — and recall must not move.

Measured on the live lattice (2,912 embedded nodes) before this change:

    JSON parse of 2000 embeddings   1231 ms      140 MB on disk
    stdlib array decode             34 ms         31 MB     (36x faster)

The 2,000-row cap in `find_nodes_by_embedding` exists to bound that parse cost,
and it is ordered by SALIENCE — not relevance — so 637 embedded nodes could
never be recalled no matter how well they matched. Among them: "Jon dislikes
boring, generic designs and flimsy materials". A preference invisible to recall.

Fixing the format removes the reason for the cap. But her memory is the last
place to trust a benchmark over a test, so the load-bearing assertion here is
not that it is faster — it is that the SAME QUERY RETURNS THE SAME NODES IN THE
SAME ORDER through either path.

float32 is a real narrowing: the JSON text holds full repr precision. These
tests pin the tolerance rather than pretending it is exact.
"""
from __future__ import annotations

import json
import math

import pytest

from soveryn.platform.lattice.legacy import (
    LatticeStore,
    _decode_embedding_blob,
    _encode_embedding_blob,
)


def _vec(seed: int, dim: int = 64) -> tuple[float, ...]:
    return tuple(math.sin(seed * 0.7 + i * 0.013) for i in range(dim))


# ── the format itself ───────────────────────────────────────────────────────

def test_a_vector_survives_the_round_trip_within_float32():
    original = _vec(1)
    back = _decode_embedding_blob(_encode_embedding_blob(original))
    assert len(back) == len(original)
    for a, b in zip(original, back):
        assert a == pytest.approx(b, abs=1e-6)


def test_the_blob_is_four_bytes_per_dimension():
    """If this grows, the whole reason for the change is gone."""
    assert len(_encode_embedding_blob(_vec(2, dim=4096))) == 4096 * 4


def test_empty_and_none_are_handled_not_crashed():
    assert _encode_embedding_blob(None) is None
    assert _decode_embedding_blob(None) is None
    assert _decode_embedding_blob(b"") is None


def test_a_truncated_blob_does_not_raise():
    """A half-written row must not take recall down with it."""
    assert _decode_embedding_blob(b"\x00\x01\x02") is None


# ── the property that actually matters ─────────────────────────────────────

def _seed(store: LatticeStore, n: int = 40) -> list[str]:
    ids = []
    for i in range(n):
        ids.append(store.write_node(
            "aetheria", f"memory number {i}", node_type="fact",
            embedding=_vec(i),
            provenance={"cls": "witnessed", "source": "test",
                        "confidence": 0.9, "temporal_context": "t",
                        "generator": "test"},
        ))
    return ids


def test_recall_returns_the_same_nodes_in_the_same_order(tmp_path):
    """The load-bearing test: the format changed, the answers did not."""
    store = LatticeStore(tmp_path / "lattice.db")
    _seed(store)
    query = _vec(7)

    binary = store.find_nodes_by_embedding("aetheria", query, limit=10, threshold=0.0)

    # Force the legacy path by clearing the blobs, leaving only JSON text.
    with store._conn() as conn:                       # noqa: SLF001 — test reaches in deliberately
        conn.execute("UPDATE nodes SET embedding_f32 = NULL")
    legacy = store.find_nodes_by_embedding("aetheria", query, limit=10, threshold=0.0)

    assert [n.id for n, _ in binary] == [n.id for n, _ in legacy]
    for (_, a), (_, b) in zip(binary, legacy):
        assert a == pytest.approx(b, abs=1e-5)


def test_a_node_written_before_the_column_existed_is_still_recalled(tmp_path):
    """Backfill is not instant; JSON-only rows must keep working meanwhile."""
    store = LatticeStore(tmp_path / "lattice.db")
    node_id = store.write_node("aetheria", "older memory", node_type="fact",
                               embedding=_vec(3))
    with store._conn() as conn:                       # noqa: SLF001
        conn.execute("UPDATE nodes SET embedding_f32 = NULL WHERE id = ?", (node_id,))
    hits = store.find_nodes_by_embedding("aetheria", _vec(3), limit=5, threshold=0.0)
    assert node_id in [n.id for n, _ in hits]


def test_backfill_populates_missing_blobs_and_is_idempotent(tmp_path):
    store = LatticeStore(tmp_path / "lattice.db")
    _seed(store, 12)
    with store._conn() as conn:                       # noqa: SLF001
        conn.execute("UPDATE nodes SET embedding_f32 = NULL")

    assert store.backfill_embedding_blobs() == 12
    assert store.backfill_embedding_blobs() == 0, "a second run must be a no-op"

    with store._conn() as conn:                       # noqa: SLF001
        missing = conn.execute(
            "SELECT COUNT(*) c FROM nodes "
            "WHERE embedding IS NOT NULL AND embedding_f32 IS NULL"
        ).fetchone()["c"]
    assert missing == 0


def test_writing_a_node_populates_both_formats(tmp_path):
    """JSON stays as the rollback path until this change has proven itself."""
    store = LatticeStore(tmp_path / "lattice.db")
    node_id = store.write_node("aetheria", "m", node_type="fact", embedding=_vec(5))
    with store._conn() as conn:                       # noqa: SLF001
        row = conn.execute(
            "SELECT embedding, embedding_f32 FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
    assert row["embedding_f32"] is not None
    assert json.loads(row["embedding"])


def test_low_salience_nodes_are_reachable(tmp_path):
    """The 637: excluded by a salience-ordered cap, not by any policy."""
    store = LatticeStore(tmp_path / "lattice.db")
    target = store.write_node("aetheria", "Jon dislikes flimsy materials",
                              node_type="fact", embedding=_vec(99), intensity=0.05)
    for i in range(30):
        store.write_node("aetheria", f"louder memory {i}", node_type="fact",
                         embedding=_vec(i), intensity=0.99)

    hits = store.find_nodes_by_embedding("aetheria", _vec(99), limit=5, threshold=0.0)
    assert target in [n.id for n, _ in hits], (
        "a perfectly matching node was unreachable because its salience was low"
    )


def test_every_eligible_node_is_a_candidate(tmp_path):
    """Directly pins the removed cap.

    `test_low_salience_nodes_are_reachable` shows relevance beats salience, but
    it seeds 31 nodes — it would have passed with the 2,000-row cap still in
    place. This asserts the candidate set is not truncated at all: every node
    with an embedding must be scored, so a query with no threshold returns all
    of them.
    """
    store = LatticeStore(tmp_path / "lattice.db")
    written = _seed(store, 60)
    hits = store.find_nodes_by_embedding(
        "aetheria", _vec(1), limit=1000, threshold=-1.0
    )
    assert len(hits) == len(written), (
        f"only {len(hits)} of {len(written)} nodes were scored — "
        "the candidate set is being truncated"
    )


def test_results_are_ordered_by_similarity_not_salience(tmp_path):
    """The cap ordered by salience. Ranking must not."""
    store = LatticeStore(tmp_path / "lattice.db")
    best = store.write_node("aetheria", "the match", node_type="fact",
                            embedding=_vec(42), intensity=0.01)
    for i in range(20):
        store.write_node("aetheria", f"loud {i}", node_type="fact",
                         embedding=_vec(500 + i), intensity=0.99)
    hits = store.find_nodes_by_embedding("aetheria", _vec(42), limit=3, threshold=-1.0)
    assert hits[0][0].id == best, "the closest vector did not rank first"


def test_numpy_and_pure_python_paths_rank_identically(tmp_path, monkeypatch):
    """numpy is a performance dependency. If it ever isn't there, recall must
    return the same nodes in the same order — only slower."""
    store = LatticeStore(tmp_path / "lattice.db")
    _seed(store, 40)
    query = _vec(11)

    fast = store.find_nodes_by_embedding("aetheria", query, limit=10, threshold=0.0)

    # Make `import numpy` fail inside the scorer, forcing the fallback.
    import builtins
    real_import = builtins.__import__

    def no_numpy(name, *a, **k):
        if name == "numpy":
            raise ImportError("numpy unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_numpy)
    slow = store.find_nodes_by_embedding("aetheria", query, limit=10, threshold=0.0)

    assert [n.id for n, _ in fast] == [n.id for n, _ in slow]
    for (_, a), (_, b) in zip(fast, slow):
        assert a == pytest.approx(b, abs=1e-5)
