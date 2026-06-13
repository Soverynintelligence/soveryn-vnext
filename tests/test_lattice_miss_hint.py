"""Miss Hint helper unit tests — pure lattice scan, no Aetheria tools.

The integration with Aetheria's search tools is tested separately in
test_aetheria_tools_miss_hint.py.
"""
from __future__ import annotations

import pytest

from soveryn.platform.lattice.legacy import (
    LAYER_DREAM,
    LAYER_GLOBAL,
    LAYER_LIBRARY,
    LAYER_PRIVATE,
    LatticeStore,
)
from soveryn.platform.lattice.miss_hint import (
    build_miss_hint,
    count_matches_per_layer,
    extract_query_tokens,
)


@pytest.fixture
def store(tmp_path):
    return LatticeStore(tmp_path / "test_miss_hint.db")


# ─── Token extraction ────────────────────────────────────────────────────────

def test_extract_tokens_lowercases_and_strips_short_tokens():
    out = extract_query_tokens("Find SOVERYN Scotty memo of 2026")
    # 'of' is stopword; '2026' is 4 chars so it stays; short tokens dropped
    assert "soveryn" in out
    assert "scotty" in out
    assert "memo" in out
    assert "2026" in out
    assert "of" not in out


def test_extract_tokens_drops_common_stopwords():
    out = extract_query_tokens("the and of are with was")
    assert out == ()


def test_extract_tokens_handles_empty_or_punctuation():
    assert extract_query_tokens("") == ()
    assert extract_query_tokens("???") == ()
    assert extract_query_tokens("a b c") == ()  # all too short


# ─── Per-layer count ─────────────────────────────────────────────────────────

def test_count_matches_per_layer_returns_all_layers_even_when_zero(store):
    counts = count_matches_per_layer(store, "aetheria", "totally absent term")
    assert set(counts.keys()) == {LAYER_LIBRARY, LAYER_GLOBAL, LAYER_PRIVATE, LAYER_DREAM}
    assert all(v == 0 for v in counts.values())


def test_count_matches_finds_node_by_content_token(store):
    """A library-layer node with 'gizmotron' in content must surface as
    a library hit when the query mentions gizmotron."""
    store.write_node(
        "aetheria", "the gizmotron user manual lives here",
        node_type="fact", layer=LAYER_LIBRARY,
    )
    counts = count_matches_per_layer(store, "aetheria", "gizmotron manual")
    assert counts[LAYER_LIBRARY] == 1
    assert counts[LAYER_GLOBAL] == 0
    assert counts[LAYER_PRIVATE] == 0
    assert counts[LAYER_DREAM] == 0


def test_count_matches_finds_node_by_tag_token(store):
    """A node whose CONTENT lacks the token but whose TAG carries it
    must still be found — the tag scan branch."""
    store.write_node(
        "aetheria", "regular text without the hint word",
        node_type="fact", layer=LAYER_GLOBAL,
        tags=("flunkbird",),
    )
    counts = count_matches_per_layer(store, "aetheria", "flunkbird investigation")
    assert counts[LAYER_GLOBAL] == 1


def test_count_matches_excludes_other_agents_in_private_layer(store):
    """Vett's private nodes do NOT count for Aetheria's miss hint."""
    store.write_node(
        "vett", "vett private about scotty rename memo",
        node_type="fact", layer=LAYER_PRIVATE,
    )
    counts = count_matches_per_layer(store, "aetheria", "scotty rename memo")
    assert counts[LAYER_PRIVATE] == 0


def test_count_matches_includes_other_agents_in_global_layer(store):
    """Global-layer nodes are everyone's — Vett's global content counts
    toward Aetheria's miss hint and vice versa."""
    store.write_node(
        "vett", "global news about scotty rename memo 2026",
        node_type="fact", layer=LAYER_GLOBAL,
    )
    counts = count_matches_per_layer(store, "aetheria", "scotty rename memo")
    assert counts[LAYER_GLOBAL] == 1


def test_count_matches_excludes_historical_snapshot_rows(store):
    """historical_snapshot tagging excludes the row from current-state
    miss hints (mirrors the production substrate filter)."""
    store.write_node(
        "aetheria", "old chronicle about rename scotty 2026",
        node_type="fact", layer=LAYER_GLOBAL,
        tags=("historical_snapshot",),
    )
    counts = count_matches_per_layer(store, "aetheria", "rename scotty 2026")
    assert counts[LAYER_GLOBAL] == 0


def test_count_matches_with_empty_tokens_returns_all_zero(store):
    """If extraction yields zero tokens (e.g., all stopwords), the count
    falls through to all-zero — we do NOT scan the whole table for nothing."""
    store.write_node("aetheria", "real content", node_type="fact", layer=LAYER_LIBRARY)
    counts = count_matches_per_layer(store, "aetheria", "the of and is to")
    assert counts[LAYER_LIBRARY] == 0


# ─── Hint payload shape ──────────────────────────────────────────────────────

def test_build_miss_hint_returns_layer_counts_and_tokens(store):
    store.write_node(
        "aetheria", "memo about scotty tinker rename 2026 05 02",
        node_type="fact", layer=LAYER_GLOBAL,
    )
    hint = build_miss_hint(store, "aetheria", "scotty rename 2026 tinker memo")
    assert "layer_counts" in hint
    assert "tokens_probed" in hint
    assert hint["layer_counts"][LAYER_GLOBAL] == 1
    assert "scotty" in hint["tokens_probed"]
    assert "rename" in hint["tokens_probed"]


def test_build_miss_hint_caps_tokens_probed_list_length(store):
    """Long queries shouldn't dump 50 tokens into the JSON; cap at 10."""
    big_query = " ".join(f"word{i}" for i in range(50))
    hint = build_miss_hint(store, "aetheria", big_query)
    assert len(hint["tokens_probed"]) <= 10
