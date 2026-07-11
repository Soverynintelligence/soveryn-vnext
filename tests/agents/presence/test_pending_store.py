"""Tests for PendingStore: durable, cross-process pending drafts + reply queue."""

from __future__ import annotations

from soveryn.agents.presence.drafting import Draft
from soveryn.agents.presence.pending_store import PendingStore


def _draft(**overrides) -> Draft:
    fields = dict(
        candidate_tweet_id="tid1",
        kind="topic",
        text="a post",
        based_on="(none stated)",
        in_reply_to=None,
    )
    fields.update(overrides)
    return Draft(**fields)


# ─── put_draft / get_draft ─────────────────────────────────────────────────


def test_put_get_round_trips_draft_with_in_reply_to_none(tmp_path):
    s = PendingStore(tmp_path / "p.db")
    draft = _draft(in_reply_to=None)
    s.put_draft("d1", draft)
    assert s.get_draft("d1") == draft


def test_put_get_round_trips_draft_with_in_reply_to_set(tmp_path):
    s = PendingStore(tmp_path / "p.db")
    draft = _draft(kind="mention", in_reply_to="1234", candidate_tweet_id="1234")
    s.put_draft("1234", draft)
    assert s.get_draft("1234") == draft


def test_get_missing_draft_returns_none(tmp_path):
    s = PendingStore(tmp_path / "p.db")
    assert s.get_draft("nope") is None


def test_put_draft_upserts_by_draft_id(tmp_path):
    s = PendingStore(tmp_path / "p.db")
    s.put_draft("d1", _draft(text="first"))
    s.put_draft("d1", _draft(text="second"))
    assert s.get_draft("d1").text == "second"


# ─── draft_ids / delete_draft ───────────────────────────────────────────────


def test_draft_ids_reflects_puts_and_deletes(tmp_path):
    s = PendingStore(tmp_path / "p.db")
    assert s.draft_ids() == set()
    s.put_draft("d1", _draft())
    s.put_draft("d2", _draft(candidate_tweet_id="tid2"))
    assert s.draft_ids() == {"d1", "d2"}
    s.delete_draft("d1")
    assert s.draft_ids() == {"d2"}


def test_delete_draft_missing_id_is_noop(tmp_path):
    s = PendingStore(tmp_path / "p.db")
    s.delete_draft("does-not-exist")  # must not raise
    assert s.draft_ids() == set()


# ─── enqueue_reply / take_replies ───────────────────────────────────────────


def test_take_replies_returns_fifo_order(tmp_path):
    s = PendingStore(tmp_path / "p.db")
    s.enqueue_reply("d1", "y", now="2026-07-11T00:00:00")
    s.enqueue_reply("d2", "n", now="2026-07-11T00:00:01")
    s.enqueue_reply("d3", "edited text", now="2026-07-11T00:00:02")
    assert s.take_replies() == [
        ("d1", "y"),
        ("d2", "n"),
        ("d3", "edited text"),
    ]


def test_take_replies_drains_the_queue(tmp_path):
    s = PendingStore(tmp_path / "p.db")
    s.enqueue_reply("d1", "y", now="2026-07-11T00:00:00")
    first = s.take_replies()
    second = s.take_replies()
    assert first == [("d1", "y")]
    assert second == []


def test_take_replies_empty_queue_returns_empty_list(tmp_path):
    s = PendingStore(tmp_path / "p.db")
    assert s.take_replies() == []
