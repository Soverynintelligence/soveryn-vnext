"""Tests for soveryn.memory.lattice. Uses tmp_path — never production."""

import json
from unittest.mock import patch
import pytest

from soveryn.memory.lattice import (
    LatticeStore, LatticeError,
    LAYER_PRIVATE, LAYER_GLOBAL, LAYER_LIBRARY, WRITE_LAYERS,
    INTENSITY_DEFAULT, _cosine, embed_text,
)


@pytest.fixture
def store(tmp_path):
    return LatticeStore(tmp_path / "test_lattice.db")


def test_write_and_read_round_trip(store):
    nid = store.write_node("aetheria", "hello world", node_type="fact",
                            intensity=0.5, tags=("greeting",),
                            embedding=(0.1, 0.2, 0.3), intent="test")
    node = store.get_node(nid)
    assert node is not None
    assert node.content == "hello world"
    assert node.layer == LAYER_PRIVATE
    assert node.tags == ("greeting",)
    assert node.embedding == (0.1, 0.2, 0.3)
    assert node.intent == "test"


def test_write_with_provenance_round_trip(store):
    prov = {"source_type": "witnessed", "region": "screen", "confidence": 0.9}
    nid = store.write_node("aetheria", "x", provenance=prov)
    node = store.get_node(nid)
    assert node.provenance == prov


@pytest.mark.parametrize("layer", ["private", "global", "library"])
def test_write_accepts_valid_layers(store, layer):
    nid = store.write_node("aetheria", "x", layer=layer)
    assert store.get_node(nid).layer == layer


@pytest.mark.parametrize("bad_layer", ["lattice", "core", "PRIVATE", "", "made_up"])
def test_write_rejects_invalid_layers(store, bad_layer):
    with pytest.raises(LatticeError, match="layer="):
        store.write_node("aetheria", "x", layer=bad_layer)


def test_read_accepts_legacy_layer_values(store):
    """Production has layer='lattice' rows. Reads must tolerate it (Jon constraint 4)."""
    import sqlite3
    with sqlite3.connect(str(store.db_path)) as conn:
        conn.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, "
            "access_count, tags, created_at, updated_at) "
            "VALUES ('legacy-id', 'fact', 'lattice', 'aetheria', 'x', 0.3, 0.3, 0, '[]', 'now', 'now')"
        )
        conn.commit()
    node = store.get_node("legacy-id")
    assert node is not None
    assert node.layer == "lattice"


@pytest.mark.parametrize("intensity", [-0.1, 1.1, 2.0])
def test_write_rejects_out_of_range_intensity(store, intensity):
    with pytest.raises(LatticeError, match="intensity"):
        store.write_node("aetheria", "x", intensity=intensity)


def test_get_node_missing_returns_none(store):
    assert store.get_node("does-not-exist") is None


def test_iter_nodes_returns_all_rows_in_deterministic_order(store):
    first = store.write_node("aetheria", "first", node_type="fact")
    second = store.write_node("vett", "second", node_type="event")

    nodes = store.iter_nodes()

    assert [node.id for node in nodes] == [first, second]
    assert [node.content for node in nodes] == ["first", "second"]


def test_iter_nodes_filters_by_agent(store):
    store.write_node("aetheria", "aetheria node")
    store.write_node("vett", "vett node")

    nodes = store.iter_nodes(agent="aetheria")

    assert [node.content for node in nodes] == ["aetheria node"]


def test_iter_nodes_can_exclude_library_rows(store):
    store.write_node("aetheria", "private node", layer=LAYER_PRIVATE)
    store.write_node("aetheria", "library node", layer=LAYER_LIBRARY)

    nodes = store.iter_nodes(include_library=False)

    assert [node.content for node in nodes] == ["private node"]


def test_iter_nodes_preserves_legacy_layer_values(store):
    import sqlite3
    with sqlite3.connect(str(store.db_path)) as conn:
        conn.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, "
            "access_count, tags, created_at, updated_at) "
            "VALUES ('legacy-layer', 'fact', 'core', 'aetheria', 'legacy', 0.3, 0.3, 0, '[]', 'now', 'now')"
        )
        conn.commit()

    nodes = store.iter_nodes()

    assert len(nodes) == 1
    assert nodes[0].layer == "core"


def test_iter_nodes_tolerates_malformed_optional_json(store):
    import sqlite3
    with sqlite3.connect(str(store.db_path)) as conn:
        conn.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, "
            "access_count, tags, created_at, updated_at, embedding, provenance) "
            "VALUES ('bad-json', 'fact', 'private', 'aetheria', 'bad json', 0.3, 0.3, 0, "
            "'NOT_JSON', 'now', 'now', '[0.1, NOPE', '{bad')"
        )
        conn.commit()

    node = store.iter_nodes()[0]

    assert node.tags == ()
    assert node.embedding is None
    assert node.provenance is None


def test_keyword_search_matches_content(store):
    store.write_node("aetheria", "rainy day in Boston", intensity=0.5)
    store.write_node("aetheria", "sunny day in Miami", intensity=0.4)
    matches = store.find_nodes_by_keywords("aetheria", "boston")
    assert len(matches) == 1
    assert "Boston" in matches[0].content


def test_keyword_search_matches_tags(store):
    store.write_node("aetheria", "x", tags=("alpha", "beta"))
    matches = store.find_nodes_by_keywords("aetheria", "alpha")
    assert len(matches) == 1


def test_keyword_search_orders_by_salience_desc(store):
    store.write_node("aetheria", "match low", intensity=0.2)
    store.write_node("aetheria", "match high", intensity=0.8)
    matches = store.find_nodes_by_keywords("aetheria", "match")
    assert matches[0].content == "match high"


def test_keyword_search_includes_global_by_default(store):
    store.write_node("aetheria", "private match", layer=LAYER_PRIVATE)
    store.write_node("vett",     "global match",  layer=LAYER_GLOBAL)
    matches = store.find_nodes_by_keywords("aetheria", "match")
    assert {m.content for m in matches} == {"private match", "global match"}


def test_keyword_search_excludes_library(store):
    store.write_node("aetheria", "private match", layer=LAYER_PRIVATE)
    store.write_node("aetheria", "library match", layer=LAYER_LIBRARY)
    matches = store.find_nodes_by_keywords("aetheria", "match")
    assert {m.content for m in matches} == {"private match"}


def test_keyword_search_other_agents_private_excluded(store):
    store.write_node("vett", "vett private", layer=LAYER_PRIVATE)
    matches = store.find_nodes_by_keywords("aetheria", "vett")
    assert matches == ()


def test_embedding_search_returns_nearest(store):
    store.write_node("aetheria", "a", embedding=(1.0, 0.0, 0.0), intensity=0.5)
    store.write_node("aetheria", "b", embedding=(0.0, 1.0, 0.0), intensity=0.5)
    store.write_node("aetheria", "c", embedding=(0.9, 0.1, 0.0), intensity=0.5)
    results = store.find_nodes_by_embedding(
        "aetheria", (1.0, 0.0, 0.0), threshold=0.5, limit=3,
    )
    assert results[0][0].content == "a"
    assert results[0][1] > results[1][1]


def test_embedding_search_skips_nodes_with_null_embedding(store):
    """Jon constraint 7."""
    store.write_node("aetheria", "no-emb", intensity=0.5)  # embedding=None
    store.write_node("aetheria", "yes-emb", embedding=(1.0, 0.0), intensity=0.5)
    results = store.find_nodes_by_embedding("aetheria", (1.0, 0.0), threshold=0.5)
    assert len(results) == 1
    assert results[0][0].content == "yes-emb"


def test_embedding_search_layer_filter_library(store):
    store.write_node("aetheria", "lib node",  layer=LAYER_LIBRARY, embedding=(1.0, 0.0))
    store.write_node("aetheria", "priv node", layer=LAYER_PRIVATE, embedding=(1.0, 0.0))
    results = store.find_nodes_by_embedding(
        "aetheria", (1.0, 0.0), threshold=0.5, layer_filter=LAYER_LIBRARY,
    )
    assert len(results) == 1
    assert results[0][0].content == "lib node"


def test_embedding_search_returns_empty_when_nothing_matches(store):
    store.write_node("aetheria", "x", embedding=(1.0, 0.0), intensity=0.5)
    results = store.find_nodes_by_embedding(
        "aetheria", (0.0, 1.0), threshold=0.99, limit=10,
    )
    assert results == ()


def test_embedding_search_excludes_historical_by_default(store):
    """Nodes tagged `historical_snapshot` are excluded from default retrieval."""
    store.write_node("aetheria", "current",   embedding=(1.0, 0.0))
    store.write_node("aetheria", "historical", embedding=(1.0, 0.0),
                     tags=("historical_snapshot",))
    results = store.find_nodes_by_embedding("aetheria", (1.0, 0.0), threshold=0.5)
    contents = {n.content for n, _ in results}
    assert contents == {"current"}, f"historical_snapshot leaked into default: {contents}"


def test_embedding_search_includes_historical_when_explicit(store):
    """include_historical=True reaches back into archival nodes."""
    store.write_node("aetheria", "current",   embedding=(1.0, 0.0))
    store.write_node("aetheria", "historical", embedding=(1.0, 0.0),
                     tags=("historical_snapshot",))
    results = store.find_nodes_by_embedding(
        "aetheria", (1.0, 0.0), threshold=0.5, include_historical=True,
    )
    contents = {n.content for n, _ in results}
    assert contents == {"current", "historical"}


def test_embedding_search_library_filter_also_respects_historical(store):
    """Library-layer queries (RAG path) also exclude historical by default."""
    store.write_node("aetheria", "lib current",     layer=LAYER_LIBRARY, embedding=(1.0, 0.0))
    store.write_node("aetheria", "lib historical",  layer=LAYER_LIBRARY, embedding=(1.0, 0.0),
                     tags=("historical_snapshot",))
    results = store.find_nodes_by_embedding(
        "aetheria", (1.0, 0.0), threshold=0.5, layer_filter=LAYER_LIBRARY,
    )
    contents = {n.content for n, _ in results}
    assert contents == {"lib current"}, f"historical_snapshot leaked: {contents}"


def test_embedding_search_historical_filter_tolerates_null_tags(store):
    """Nodes with NULL/empty tags aren't accidentally excluded."""
    store.write_node("aetheria", "no-tags", embedding=(1.0, 0.0))  # tags=None
    store.write_node("aetheria", "empty-tags", embedding=(1.0, 0.0), tags=())
    results = store.find_nodes_by_embedding("aetheria", (1.0, 0.0), threshold=0.5)
    contents = {n.content for n, _ in results}
    assert contents == {"no-tags", "empty-tags"}


def test_embedding_search_empty_db_returns_empty(store):
    results = store.find_nodes_by_embedding("aetheria", (1.0, 0.0), threshold=0.5)
    assert results == ()


# ─── Malformed embedding tolerance (Jon: prove graceful skip) ────────────────

def _raw_insert_node(db_path, *, node_id, agent, embedding_text, intensity=0.5, layer="private"):
    """Insert a node with arbitrary raw embedding text (bypassing write_node)."""
    import sqlite3
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, "
            "access_count, tags, created_at, updated_at, embedding) "
            "VALUES (?, 'fact', ?, ?, 'x', ?, ?, 0, '[]', 'now', 'now', ?)",
            (node_id, layer, agent, intensity, intensity, embedding_text),
        )
        conn.commit()


def test_embedding_search_skips_corrupt_json_embedding(store):
    """A row with truncated/corrupt JSON in embedding must not crash recall."""
    _raw_insert_node(store.db_path, node_id="corrupt-1", agent="aetheria",
                     embedding_text="[0.1, 0.2, NOT_JSON")
    store.write_node("aetheria", "good", embedding=(1.0, 0.0), intensity=0.5)
    results = store.find_nodes_by_embedding("aetheria", (1.0, 0.0), threshold=0.5)
    assert len(results) == 1
    assert results[0][0].content == "good"


def test_embedding_search_skips_non_list_embedding(store):
    """A row whose embedding JSON is a dict / scalar must be skipped, not crash."""
    _raw_insert_node(store.db_path, node_id="dict-emb", agent="aetheria",
                     embedding_text='{"unexpected": "shape"}')
    _raw_insert_node(store.db_path, node_id="scalar-emb", agent="aetheria",
                     embedding_text='42')
    store.write_node("aetheria", "ok", embedding=(1.0, 0.0), intensity=0.5)
    results = store.find_nodes_by_embedding("aetheria", (1.0, 0.0), threshold=0.5)
    assert {r[0].content for r in results} == {"ok"}


def test_embedding_search_skips_non_numeric_elements(store):
    """A row whose embedding has non-float elements must be skipped, not crash."""
    _raw_insert_node(store.db_path, node_id="strs-emb", agent="aetheria",
                     embedding_text='["not", "a", "vector"]')
    store.write_node("aetheria", "ok", embedding=(1.0, 0.0), intensity=0.5)
    results = store.find_nodes_by_embedding("aetheria", (1.0, 0.0), threshold=0.5)
    assert {r[0].content for r in results} == {"ok"}


def test_embedding_search_handles_wrong_length_embedding(store):
    """Different-length embeddings score 0 (cosine length-mismatch), filtered by threshold."""
    store.write_node("aetheria", "len-2", embedding=(1.0, 0.0), intensity=0.5)
    store.write_node("aetheria", "len-3", embedding=(1.0, 0.0, 0.0), intensity=0.5)
    # Query with length-2; len-2 matches exactly, len-3 scores 0 and is filtered
    results = store.find_nodes_by_embedding("aetheria", (1.0, 0.0), threshold=0.5)
    assert {r[0].content for r in results} == {"len-2"}


def test_embedding_search_handles_empty_list_embedding(store):
    """An empty embedding list must not crash, scores 0 vs anything, filtered."""
    _raw_insert_node(store.db_path, node_id="empty-emb", agent="aetheria",
                     embedding_text='[]')
    store.write_node("aetheria", "ok", embedding=(1.0, 0.0), intensity=0.5)
    results = store.find_nodes_by_embedding("aetheria", (1.0, 0.0), threshold=0.5)
    assert {r[0].content for r in results} == {"ok"}


def test_get_node_with_corrupt_embedding_returns_none_embedding(store):
    """get_node on a corrupt-embedding row returns the node with embedding=None,
    rather than crashing on json.loads."""
    _raw_insert_node(store.db_path, node_id="corrupt-getn", agent="aetheria",
                     embedding_text="not valid json {{{")
    node = store.get_node("corrupt-getn")
    assert node is not None
    assert node.embedding is None


def test_get_node_with_corrupt_tags_returns_empty_tuple(store):
    """get_node on a corrupt-tags row returns tags=() rather than crashing."""
    import sqlite3
    with sqlite3.connect(str(store.db_path)) as conn:
        conn.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, "
            "access_count, tags, created_at, updated_at) "
            "VALUES ('corrupt-tags', 'fact', 'private', 'aetheria', 'x', 0.5, 0.5, 0, "
            "'[malformed', 'now', 'now')"
        )
        conn.commit()
    node = store.get_node("corrupt-tags")
    assert node is not None
    assert node.tags == ()


def test_get_node_with_corrupt_provenance_returns_none(store):
    """get_node on a corrupt-provenance row returns provenance=None."""
    import sqlite3
    with sqlite3.connect(str(store.db_path)) as conn:
        conn.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, "
            "access_count, tags, created_at, updated_at, provenance) "
            "VALUES ('corrupt-prov', 'fact', 'private', 'aetheria', 'x', 0.5, 0.5, 0, "
            "'[]', 'now', 'now', 'not json')"
        )
        conn.commit()
    node = store.get_node("corrupt-prov")
    assert node is not None
    assert node.provenance is None


def test_cosine_handles_zero_vector():
    assert _cosine((0.0, 0.0), (1.0, 1.0)) == 0.0
    assert _cosine((1.0, 1.0), (0.0, 0.0)) == 0.0


def test_cosine_handles_mismatched_lengths():
    assert _cosine((1.0,), (1.0, 0.0)) == 0.0


def test_cosine_identity():
    assert _cosine((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)


def test_embedding_stored_as_json_text(store):
    """Production stores embeddings as TEXT (JSON-encoded). Mirror format."""
    import sqlite3
    nid = store.write_node("aetheria", "x", embedding=(0.1, 0.2, 0.3))
    with sqlite3.connect(str(store.db_path)) as conn:
        row = conn.execute(
            "SELECT typeof(embedding), embedding FROM nodes WHERE id = ?",
            (nid,),
        ).fetchone()
    assert row[0] == "text"
    assert json.loads(row[1]) == [0.1, 0.2, 0.3]


def test_embed_text_routes_through_client(store):
    """embed_text() calls soveryn.inference.llama_server_client.embed()."""
    from soveryn.inference.llama_server_client import EmbeddingResponse
    fake = EmbeddingResponse(vectors=((0.5, 0.6, 0.7),), usage=None, raw={})
    with patch("soveryn.inference.llama_server_client.embed", return_value=fake) as m:
        v = embed_text("hello")
    assert v == (0.5, 0.6, 0.7)
    assert m.call_count == 1


def test_store_never_writes_outside_injected_path(store, tmp_path):
    assert str(store.db_path).startswith(str(tmp_path))


def test_write_layers_constant():
    assert WRITE_LAYERS == {"private", "global", "library"}
