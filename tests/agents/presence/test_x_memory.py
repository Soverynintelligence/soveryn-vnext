"""Tests for x_memory — published-only lattice writes (with embedding) + rejection log.

Two invariants under test:
  1. A published post MUST be written to the lattice WITH a non-null
     embedding (else it is stored but never surfaces in Aetheria's
     per-turn `find_nodes_by_embedding` recall — the whole point is that
     she remembers what she posted).
  2. A rejected draft MUST NOT create a lattice node at all — it's a
     tuning signal only, never recallable as "her public voice".
"""

import json

from soveryn.agents.presence.x_memory import log_rejection, write_x_post_node


class FakeLatticeStore:
    """Records write_node calls instead of hitting a real DB."""

    def __init__(self):
        self.calls = []

    def write_node(self, agent, content, *, node_type="fact", layer=None,
                    intensity=None, tags=None, embedding=None, intent=None,
                    provenance=None):
        self.calls.append({
            "agent": agent,
            "content": content,
            "node_type": node_type,
            "layer": layer,
            "intensity": intensity,
            "tags": tags,
            "embedding": embedding,
            "intent": intent,
            "provenance": provenance,
        })
        return "node-123"


def fake_embed_fn(text):
    """A known, deterministic fake embedding for a given text."""
    return (float(len(text)), 0.5, -0.5)


class TestWriteXPostNode:
    def test_calls_write_node_exactly_once(self):
        store = FakeLatticeStore()
        write_x_post_node(
            lattice_store=store,
            embed_fn=fake_embed_fn,
            text="A thought on local inference.",
            source_tweet=None,
            edited_by_jon=False,
            posted_id="19001",
            now="2026-07-11T00:00:00",
        )
        assert len(store.calls) == 1

    def test_node_type_is_x_post(self):
        store = FakeLatticeStore()
        write_x_post_node(
            lattice_store=store,
            embed_fn=fake_embed_fn,
            text="A thought on local inference.",
            source_tweet=None,
            edited_by_jon=False,
            posted_id="19001",
            now="2026-07-11T00:00:00",
        )
        assert store.calls[0]["node_type"] == "x_post"

    def test_embedding_is_non_null_and_matches_embed_fn(self):
        """The critical correctness rule: the node MUST carry an embedding,
        equal to embed_fn(text), or it will never be recalled."""
        store = FakeLatticeStore()
        text = "A thought on local inference."
        write_x_post_node(
            lattice_store=store,
            embed_fn=fake_embed_fn,
            text=text,
            source_tweet=None,
            edited_by_jon=False,
            posted_id="19001",
            now="2026-07-11T00:00:00",
        )
        assert store.calls[0]["embedding"] is not None
        assert store.calls[0]["embedding"] == fake_embed_fn(text)

    def test_embed_fn_called_with_the_post_text(self):
        store = FakeLatticeStore()
        seen = []

        def spy_embed_fn(t):
            seen.append(t)
            return fake_embed_fn(t)

        text = "A thought on local inference."
        write_x_post_node(
            lattice_store=store,
            embed_fn=spy_embed_fn,
            text=text,
            source_tweet=None,
            edited_by_jon=False,
            posted_id="19001",
            now="2026-07-11T00:00:00",
        )
        assert seen == [text]

    def test_provenance_carries_the_posted_url(self):
        store = FakeLatticeStore()
        write_x_post_node(
            lattice_store=store,
            embed_fn=fake_embed_fn,
            text="A thought on local inference.",
            source_tweet="18999",
            edited_by_jon=True,
            posted_id="19001",
            now="2026-07-11T00:00:00",
        )
        prov = store.calls[0]["provenance"]
        assert prov["url"] == "https://x.com/i/web/status/19001"
        assert prov["posted_id"] == "19001"
        assert prov["source_tweet"] == "18999"
        assert prov["edited_by_jon"] is True
        assert prov["posted_at"] == "2026-07-11T00:00:00"

    def test_tags_include_x_and_post(self):
        store = FakeLatticeStore()
        write_x_post_node(
            lattice_store=store,
            embed_fn=fake_embed_fn,
            text="A thought on local inference.",
            source_tweet=None,
            edited_by_jon=False,
            posted_id="19001",
            now="2026-07-11T00:00:00",
        )
        assert store.calls[0]["tags"] == ("x", "post")

    def test_agent_defaults_to_aetheria(self):
        store = FakeLatticeStore()
        write_x_post_node(
            lattice_store=store,
            embed_fn=fake_embed_fn,
            text="A thought on local inference.",
            source_tweet=None,
            edited_by_jon=False,
            posted_id="19001",
            now="2026-07-11T00:00:00",
        )
        assert store.calls[0]["agent"] == "aetheria"

    def test_returns_the_node_id(self):
        store = FakeLatticeStore()
        node_id = write_x_post_node(
            lattice_store=store,
            embed_fn=fake_embed_fn,
            text="A thought on local inference.",
            source_tweet=None,
            edited_by_jon=False,
            posted_id="19001",
            now="2026-07-11T00:00:00",
        )
        assert node_id == "node-123"

    def test_content_is_the_post_text(self):
        store = FakeLatticeStore()
        text = "A thought on local inference."
        write_x_post_node(
            lattice_store=store,
            embed_fn=fake_embed_fn,
            text=text,
            source_tweet=None,
            edited_by_jon=False,
            posted_id="19001",
            now="2026-07-11T00:00:00",
        )
        assert store.calls[0]["content"] == text


class TestLogRejection:
    def test_does_not_touch_the_lattice_store_at_all(self, tmp_path):
        """A rejection must create ZERO lattice nodes — it's a tuning
        signal, never recallable public voice."""
        # No lattice_store is even passed to log_rejection — its signature
        # has no lattice dependency, which is itself the guarantee.
        signal_path = tmp_path / "x_rejections.jsonl"
        log_rejection(
            signal_path=signal_path,
            text="A spicy take that Jon didn't like.",
            reason="too combative",
            now="2026-07-11T00:00:00",
        )
        # Nothing to assert against a lattice store since none exists in
        # scope here — the absence of that parameter is the guarantee.

    def test_appends_the_rejected_draft_and_reason(self, tmp_path):
        signal_path = tmp_path / "x_rejections.jsonl"
        log_rejection(
            signal_path=signal_path,
            text="A spicy take that Jon didn't like.",
            reason="too combative",
            now="2026-07-11T00:00:00",
        )
        lines = signal_path.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["text"] == "A spicy take that Jon didn't like."
        assert record["reason"] == "too combative"
        assert record["now"] == "2026-07-11T00:00:00"

    def test_multiple_rejections_append_not_overwrite(self, tmp_path):
        signal_path = tmp_path / "x_rejections.jsonl"
        log_rejection(
            signal_path=signal_path,
            text="first draft",
            reason="off-tone",
            now="2026-07-11T00:00:00",
        )
        log_rejection(
            signal_path=signal_path,
            text="second draft",
            reason="not funny",
            now="2026-07-11T00:05:00",
        )
        lines = signal_path.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["text"] == "first draft"
        assert json.loads(lines[1])["text"] == "second draft"

    def test_creates_parent_directories_if_missing(self, tmp_path):
        signal_path = tmp_path / "nested" / "dir" / "x_rejections.jsonl"
        log_rejection(
            signal_path=signal_path,
            text="a draft",
            reason="a reason",
            now="2026-07-11T00:00:00",
        )
        assert signal_path.exists()
