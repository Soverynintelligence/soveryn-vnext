"""Tests for PresenceDaemonSurface — scan_once / resolve_reply / run_forever.

All edges are faked (FakeX, draft_fn, send_fn): no network, no model call.
"""

from __future__ import annotations

import sqlite3

import pytest

from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.daemon import PresenceDaemonSurface, _interruptible_sleep
from soveryn.agents.presence.pending_store import PendingStore
from soveryn.agents.presence.signal_log import SignalLog
from soveryn.agents.presence.x_client import Tweet, XClientError


def _status_of(tmp_path, tweet_id):
    conn = sqlite3.connect(str(tmp_path / "c.db"))
    row = conn.execute(
        "SELECT status FROM candidates WHERE tweet_id = ?", (tweet_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def _kind_of(tmp_path, tweet_id):
    conn = sqlite3.connect(str(tmp_path / "c.db"))
    row = conn.execute(
        "SELECT kind FROM candidates WHERE tweet_id = ?", (tweet_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


class FakeX:
    def __init__(self, tweets):
        self.tweets, self.posted = tweets, []

    def search_recent(self, q, since_id=None):
        return self.tweets

    def create_tweet(self, text):
        self.posted.append(text)
        return "p1"

    def reply_tweet(self, text, in_reply_to):
        self.posted.append(text)
        return "p2"


def _cfg(tmp_path, **overrides):
    base = PresenceConfig.default()
    return base.__class__(**{**base.__dict__, "db_path": tmp_path / "c.db",
                              "signal_log_path": tmp_path / "s.db", **overrides})


def _daemon(tmp_path, tweets, draft_fn, sent, **cfg_overrides):
    cfg = _cfg(tmp_path, **cfg_overrides)
    return PresenceDaemonSurface(
        cfg=cfg,
        x_client=FakeX(tweets),
        store=CandidateStore(tmp_path / "c.db"),
        draft_fn=draft_fn,
        send_fn=lambda m: sent.append(m),
        signal_log=SignalLog(tmp_path / "s.db"),
        pending_store=PendingStore(tmp_path / "pending.db"),
    )


class FailingCreateFakeX(FakeX):
    """FakeX whose posting calls always raise, to exercise a failed publish."""

    def create_tweet(self, text):
        raise XClientError("X API 500: server error")

    def reply_tweet(self, text, in_reply_to):
        raise XClientError("X API 500: server error")


_DRAFT_FN = lambda p: '{"post":"grounded.","based_on":"data","skip":false}'
_SKIP_FN = lambda p: '{"post":"","based_on":"","skip":true}'


# ─── scan_once ──────────────────────────────────────────────────────────────


def test_scan_sends_draft_for_relevant_tweet(tmp_path):
    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], _DRAFT_FN, sent)
    assert d.scan_once() == 1 and len(sent) == 1


def test_scan_dedups_across_niche_terms_and_mention_search(tmp_path):
    # The same tweet id would otherwise be re-ingested for every one of the
    # 10 niche-term searches plus the mention search (11 calls in FakeX).
    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], _DRAFT_FN, sent)
    d.scan_once()
    assert len(d.pending_store.draft_ids()) == 1


def test_scan_below_threshold_tweet_is_not_drafted(tmp_path):
    sent = []
    cfg = _cfg(tmp_path)
    tweet = Tweet("1", "a", "completely unrelated text", "u")

    class NoMentionsFakeX(FakeX):
        # Distinguish the niche-term searches from the own-handle mention
        # search, unlike the shared FakeX (which returns the same tweets for
        # every query) — needed here because a bare mention boost alone
        # (3.0) would clear the default threshold (2.0) regardless of topic
        # relevance, masking the below-threshold case this test targets.
        def search_recent(self, q, since_id=None):
            return [] if q == f"@{cfg.own_handle}" else self.tweets

    d = PresenceDaemonSurface(
        cfg=cfg,
        x_client=NoMentionsFakeX([tweet]),
        store=CandidateStore(tmp_path / "c.db"),
        draft_fn=_DRAFT_FN,
        send_fn=lambda m: sent.append(m),
        signal_log=SignalLog(tmp_path / "s.db"),
        pending_store=PendingStore(tmp_path / "pending.db"),
    )
    assert d.scan_once() == 0
    assert d.pending_store.draft_ids() == set()
    assert sent == []


def test_scan_respects_max_drafts_per_scan(tmp_path):
    sent = []
    tweets = [Tweet(str(i), "a", "sovereign AI local LLM", "u") for i in range(5)]
    d = _daemon(tmp_path, tweets, _DRAFT_FN, sent, max_drafts_per_scan=2)
    assert d.scan_once() == 2
    assert len(d.pending_store.draft_ids()) == 2


def test_scan_skip_draft_does_not_add_to_pending(tmp_path):
    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], _SKIP_FN, sent)
    assert d.scan_once() == 0
    assert d.pending_store.draft_ids() == set()
    assert sent == []


def test_scan_draft_id_is_deterministic_tweet_id(tmp_path):
    sent = []
    d = _daemon(tmp_path, [Tweet("42", "a", "sovereign AI local LLM", "u")], _DRAFT_FN, sent)
    d.scan_once()
    assert d.pending_store.draft_ids() == {"42"}


def test_scan_skip_marks_candidate_skipped_and_is_not_redrafted(tmp_path):
    # Finding 3: a candidate whose draft_fn returns skip must leave "pending"
    # (a terminal "skipped" status) or it re-surfaces via pending_ranked on
    # every subsequent scan and re-runs the model for free.
    calls = []

    def counting_skip_fn(prompt):
        calls.append(prompt)
        return '{"post":"","based_on":"","skip":true}'

    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], counting_skip_fn, sent)

    d.scan_once()
    assert _status_of(tmp_path, "1") == "skipped"
    assert len(calls) == 1

    d.scan_once()
    assert len(calls) == 1  # draft_fn must not be called again for a skipped candidate


def test_niche_rich_mention_ingested_as_mention_not_topic(tmp_path):
    # Finding 5: a tweet that both @-mentions the handle AND contains niche
    # terms must be stored kind="mention" (own-handle search runs first), not
    # "topic" — otherwise it loses its reply linkage and mention boost.
    sent = []
    tweet = Tweet("1", "a", "sovereign AI local LLM @Soveryn_AI what do you think?", "u")
    d = _daemon(tmp_path, [tweet], _DRAFT_FN, sent)
    d.scan_once()

    assert _kind_of(tmp_path, "1") == "mention"

    draft_id = next(iter(d.pending_store.draft_ids()))
    assert d.pending_store.get_draft(draft_id).kind == "mention"
    assert d.pending_store.get_draft(draft_id).in_reply_to == "1"


# ─── resolve_reply ──────────────────────────────────────────────────────────


def test_resolve_approve_publishes(tmp_path):
    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], _DRAFT_FN, sent)
    d.scan_once()
    draft_id = next(iter(d.pending_store.draft_ids()))
    r = d.resolve_reply(draft_id, "y")
    assert r.ok and d.x_client.posted == ["grounded."]


def test_resolve_approve_removes_from_pending(tmp_path):
    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], _DRAFT_FN, sent)
    d.scan_once()
    draft_id = next(iter(d.pending_store.draft_ids()))
    d.resolve_reply(draft_id, "y")
    assert d.pending_store.get_draft(draft_id) is None


def test_resolve_reject_no_publish(tmp_path):
    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], _DRAFT_FN, sent)
    d.scan_once()
    assert d.resolve_reply(next(iter(d.pending_store.draft_ids())), "n") is None
    assert d.x_client.posted == []


def test_resolve_edit_publishes_jons_literal_text(tmp_path):
    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], _DRAFT_FN, sent)
    d.scan_once()
    draft_id = next(iter(d.pending_store.draft_ids()))
    r = d.resolve_reply(draft_id, "my own words instead")
    assert r.ok and d.x_client.posted == ["my own words instead"]


def test_resolve_unknown_draft_id_returns_none(tmp_path):
    sent = []
    d = _daemon(tmp_path, [], _DRAFT_FN, sent)
    assert d.resolve_reply("does-not-exist", "y") is None


def test_resolve_logs_every_outcome_to_signal_log(tmp_path):
    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], _DRAFT_FN, sent)
    d.scan_once()
    draft_id = next(iter(d.pending_store.draft_ids()))
    d.resolve_reply(draft_id, "y")
    records = d.signal_log.all()
    assert len(records) == 1
    assert records[0]["draft_id"] == draft_id
    assert records[0]["action"] == "approve"


def test_resolve_reject_logs_reason(tmp_path):
    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], _DRAFT_FN, sent)
    d.scan_once()
    draft_id = next(iter(d.pending_store.draft_ids()))
    d.resolve_reply(draft_id, "reject: too promotional")
    records = d.signal_log.all()
    assert records[0]["action"] == "reject"
    assert records[0]["reason"] == "too promotional"


def test_resolve_approve_publish_failure_leaves_draft_pending_for_retry(tmp_path):
    # A failed publish (e.g. a transient X API error) must not delete the
    # pending draft — Jon retrying "y" later needs to be able to resolve the
    # same draft_id again instead of hitting "unknown draft id".
    sent = []
    cfg = _cfg(tmp_path)
    d = PresenceDaemonSurface(
        cfg=cfg,
        x_client=FailingCreateFakeX([Tweet("1", "a", "sovereign AI local LLM", "u")]),
        store=CandidateStore(tmp_path / "c.db"),
        draft_fn=_DRAFT_FN,
        send_fn=lambda m: sent.append(m),
        signal_log=SignalLog(tmp_path / "s.db"),
        pending_store=PendingStore(tmp_path / "pending.db"),
    )
    d.scan_once()
    draft_id = next(iter(d.pending_store.draft_ids()))

    r = d.resolve_reply(draft_id, "y")

    assert r.ok is False
    assert d.pending_store.get_draft(draft_id) is not None  # left for retry
    records = d.signal_log.all()
    assert len(records) == 1
    assert records[0]["action"] == "approve"


def test_drain_pending_replies_processes_enqueued_reply_end_to_end(tmp_path):
    sent = []
    d = _daemon(tmp_path, [Tweet("1", "a", "sovereign AI local LLM", "u")], _DRAFT_FN, sent)
    d.scan_once()
    draft_id = next(iter(d.pending_store.draft_ids()))
    d.pending_store.enqueue_reply(draft_id, "y", now="2026-07-11T00:00:00")

    processed = d.drain_pending_replies()

    assert processed == 1
    assert d.x_client.posted == ["grounded."]
    assert d.pending_store.get_draft(draft_id) is None
    # Drain is exhaustive: a second call finds nothing left queued.
    assert d.drain_pending_replies() == 0


def test_drain_pending_replies_bad_reply_does_not_abort_the_rest(tmp_path):
    # One resolve_reply raising must not stop the rest of the queue from
    # being drained.
    sent = []
    d = _daemon(tmp_path, [], _DRAFT_FN, sent)

    calls = []

    def flaky_resolve(draft_id, reply_text):
        calls.append(draft_id)
        if draft_id == "bad":
            raise RuntimeError("boom")
        return None

    d.resolve_reply = flaky_resolve
    d.pending_store.enqueue_reply("bad", "y", now="2026-07-11T00:00:00")
    d.pending_store.enqueue_reply("good", "y", now="2026-07-11T00:00:01")

    processed = d.drain_pending_replies()

    assert processed == 2
    assert calls == ["bad", "good"]


# ─── run_forever ────────────────────────────────────────────────────────────


def test_run_forever_can_be_bounded_for_scheduler_tests(tmp_path):
    sent = []
    d = _daemon(tmp_path, [], _DRAFT_FN, sent)
    calls = {"sleep": []}
    d.run_forever(interval_seconds=2.5, iterations=3, sleep=calls["sleep"].append)
    # Two inter-scan gaps × 2.5s = 5.0s total sleep regardless of chunking,
    # chunked into 1.0 + 1.0 + 0.5 per gap (default granularity 1.0).
    assert calls["sleep"] == [1.0, 1.0, 0.5, 1.0, 1.0, 0.5]


def test_run_forever_exits_promptly_when_stop_requested_mid_sleep(tmp_path):
    sent = []
    d = _daemon(tmp_path, [], _DRAFT_FN, sent)
    calls = {"scan": 0, "sleep_calls": 0}
    orig_scan = d.scan_once

    def counting_scan():
        calls["scan"] += 1
        return orig_scan()

    d.scan_once = counting_scan

    def fake_sleep(secs):
        calls["sleep_calls"] += 1

    stop = {"flag": False}

    def should_stop():
        if calls["sleep_calls"] >= 3:
            stop["flag"] = True
        return stop["flag"]

    d.run_forever(interval_seconds=60.0, sleep=fake_sleep, stop_requested=should_stop)

    assert calls["scan"] == 1
    assert calls["sleep_calls"] == 3


def test_interruptible_sleep_helper_polls_stop_every_granularity():
    polls = {"n": 0}

    def should_stop():
        polls["n"] += 1
        return polls["n"] >= 3

    sleeps = []
    _interruptible_sleep(duration_seconds=60.0, should_stop=should_stop,
                          sleep=sleeps.append, granularity=1.0)
    assert sleeps == [1.0, 1.0]


def test_interruptible_sleep_zero_duration_returns_immediately():
    sleeps = []
    _interruptible_sleep(duration_seconds=0.0, should_stop=lambda: False,
                          sleep=sleeps.append, granularity=1.0)
    assert sleeps == []


def test_run_forever_survives_scan_once_exception(tmp_path):
    # Finding 4: a transient exception from one scan_once (e.g. an X API
    # error) must not exit the daemon — it should be logged and the loop
    # must continue to the next iteration.
    sent = []

    class FlakyFakeX(FakeX):
        def __init__(self, tweets):
            super().__init__(tweets)
            self.calls = 0

        def search_recent(self, q, since_id=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient X error")
            return self.tweets

    cfg = _cfg(tmp_path)
    d = PresenceDaemonSurface(
        cfg=cfg,
        x_client=FlakyFakeX([]),
        store=CandidateStore(tmp_path / "c.db"),
        draft_fn=_DRAFT_FN,
        send_fn=lambda m: sent.append(m),
        signal_log=SignalLog(tmp_path / "s.db"),
        pending_store=PendingStore(tmp_path / "pending.db"),
    )

    scan_calls = {"n": 0}
    orig_scan = d.scan_once

    def counting_scan():
        scan_calls["n"] += 1
        return orig_scan()

    d.scan_once = counting_scan

    d.run_forever(iterations=2, sleep=lambda *_: None)

    assert scan_calls["n"] == 2
