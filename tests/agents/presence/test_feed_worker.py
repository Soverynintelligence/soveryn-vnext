"""Tests for XFeedWorker — isolated poll loop (search -> score -> store).

All edges are faked (FakeX / RaisingFakeX): no network, no model call, no
wall clock (now_fn is injected everywhere).
"""

from __future__ import annotations

import sqlite3

from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.feed_worker import XFeedWorker
from soveryn.agents.presence.x_client import Tweet, XClientError


def _cfg(tmp_path, **overrides):
    base = PresenceConfig.default()
    return base.__class__(
        **{
            **base.__dict__,
            "db_path": tmp_path / "c.db",
            "niche_terms": ("sovereign AI", "local LLM"),
            **overrides,
        }
    )


def _kind_of(tmp_path, tweet_id):
    conn = sqlite3.connect(str(tmp_path / "c.db"))
    row = conn.execute(
        "SELECT kind FROM candidates WHERE tweet_id = ?", (tweet_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


class FakeX:
    """Returns the same fixed tweets for every query (mention or niche)."""

    def __init__(self, tweets):
        self.tweets = tweets
        self.queries = []

    def search_recent(self, query, since_id=None):
        self.queries.append(query)
        return self.tweets


class RaisingFakeX:
    """Every search_recent call raises XClientError — simulates an X outage."""

    def __init__(self, message="X API 503: service unavailable"):
        self.message = message
        self.calls = 0

    def search_recent(self, query, since_id=None):
        self.calls += 1
        raise XClientError(self.message)


class Clock:
    """Mutable injectable now_fn; advance() moves it forward for staleness tests."""

    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def _worker(tmp_path, x_client, now_fn=None, **cfg_overrides):
    cfg = _cfg(tmp_path, **cfg_overrides)
    return XFeedWorker(
        cfg=cfg,
        x_client=x_client,
        store=CandidateStore(tmp_path / "c.db"),
        now_fn=now_fn or Clock(1000.0),
    )


# ─── poll_once ──────────────────────────────────────────────────────────────


def test_poll_once_upserts_scored_candidate_above_threshold(tmp_path):
    tweet = Tweet("1", "a", "sovereign AI and local LLM reliability", "u")
    w = _worker(tmp_path, FakeX([tweet]))
    assert w.poll_once() == 1
    assert _kind_of(tmp_path, "1") == "mention"  # mention search runs first


def test_poll_once_skips_tweet_below_score_threshold(tmp_path):
    # Single niche term = score 1.0, below default threshold 2.0.
    tweet = Tweet("1", "a", "sovereign AI is neat", "u")

    class NoMentionFakeX(FakeX):
        def search_recent(self, query, since_id=None):
            self.queries.append(query)
            return [] if query.startswith("@") else self.tweets

    w = _worker(tmp_path, NoMentionFakeX([tweet]))
    assert w.poll_once() == 0
    assert _kind_of(tmp_path, "1") is None


def test_poll_once_skips_topic_tweet_with_restricted_replies(tmp_path):
    """A topic (uninvited) tweet whose author restricts replies is skipped at
    ingest — an uninvited reply 403s at post time ("Reply to this conversation
    is not allowed") and burns a metered X credit for nothing."""
    tweet = Tweet("1", "a", "sovereign AI and local LLM reliability", "u",
                  reply_settings="following")

    class NoMentionFakeX(FakeX):
        def search_recent(self, query, since_id=None):
            self.queries.append(query)
            return [] if query.startswith("@") else self.tweets

    w = _worker(tmp_path, NoMentionFakeX([tweet]))
    assert w.poll_once() == 0
    assert _kind_of(tmp_path, "1") is None


def test_poll_once_keeps_mention_even_with_restricted_replies(tmp_path):
    """Mentions are exempt from the reply-settings filter: being mentioned
    means the author engaged her, so the reply is allowed regardless of the
    conversation's reply setting."""
    tweet = Tweet("1", "a", "sovereign AI and local LLM reliability", "u",
                  reply_settings="mentionedUsers")
    w = _worker(tmp_path, FakeX([tweet]))
    assert w.poll_once() == 1
    assert _kind_of(tmp_path, "1") == "mention"


def test_poll_once_dedups_already_seen_tweets(tmp_path):
    tweet = Tweet("1", "a", "sovereign AI and local LLM reliability", "u")
    w = _worker(tmp_path, FakeX([tweet]))
    assert w.poll_once() == 1
    # Second poll: same tweet returned by every search again, already seen.
    assert w.poll_once() == 0


def test_poll_once_dedups_within_single_call_mention_before_niche(tmp_path):
    # A tweet returned by BOTH the mention search and every niche search
    # (the shared FakeX behavior) must be stored exactly once, as a mention,
    # not once per query.
    tweet = Tweet("1", "a", "@Soveryn_AI sovereign AI and local LLM", "u")
    x = FakeX([tweet])
    w = _worker(tmp_path, x)
    assert w.poll_once() == 1
    assert x.queries[0] == "@Soveryn_AI"
    assert _kind_of(tmp_path, "1") == "mention"


def test_niche_rich_mention_ingested_as_mention_not_topic(tmp_path):
    tweet = Tweet("1", "a", "sovereign AI local LLM @Soveryn_AI thoughts?", "u")
    w = _worker(tmp_path, FakeX([tweet]))
    w.poll_once()
    assert _kind_of(tmp_path, "1") == "mention"


def test_poll_once_stores_topic_tweet_without_mention(tmp_path):
    # Topic ingestion only happens when the niche trawl is explicitly enabled.
    tweet = Tweet("1", "a", "sovereign AI and local LLM are the future", "u")

    class NoMentionFakeX(FakeX):
        def search_recent(self, query, since_id=None):
            self.queries.append(query)
            return [] if query.startswith("@") else self.tweets

    w = _worker(tmp_path, NoMentionFakeX([tweet]), trawl_niche_topics=True)
    assert w.poll_once() == 1
    assert _kind_of(tmp_path, "1") == "topic"


def test_poll_once_default_searches_only_mention_query(tmp_path):
    # With trawl_niche_topics False (the default), a poll issues ONLY the
    # @-mention search — no niche terms — and still ingests a mention normally.
    tweet = Tweet("1", "a", "@Soveryn_AI what do you think of local LLMs?", "u")
    x = FakeX([tweet])
    w = _worker(tmp_path, x)
    assert w.poll_once() == 1
    assert x.queries == ["@Soveryn_AI"]  # ONLY the mention query, no niche terms
    assert _kind_of(tmp_path, "1") == "mention"


def test_poll_once_trawl_flag_runs_niche_searches(tmp_path):
    # Back-compat: with the flag True, the niche searches still run.
    tweet = Tweet("1", "a", "@Soveryn_AI sovereign AI local LLM", "u")
    x = FakeX([tweet])
    w = _worker(tmp_path, x, trawl_niche_topics=True)
    w.poll_once()
    assert x.queries == ["@Soveryn_AI", "sovereign AI", "local LLM"]


def test_poll_once_client_error_does_not_raise_and_returns_zero(tmp_path):
    w = _worker(tmp_path, RaisingFakeX())
    assert w.poll_once() == 0  # must not raise


# ─── status ─────────────────────────────────────────────────────────────────


def test_status_before_any_poll_is_stale_with_no_last_ok(tmp_path):
    w = _worker(tmp_path, FakeX([]))
    status = w.status()
    assert status == {"last_ok_ts": None, "consecutive_errors": 0, "stale": True}


def test_status_records_error_and_increments_consecutive_errors(tmp_path):
    w = _worker(tmp_path, RaisingFakeX())
    w.poll_once()
    w.poll_once()
    status = w.status()
    assert status["consecutive_errors"] == 2
    assert status["last_ok_ts"] is None


def test_status_success_resets_consecutive_errors_and_sets_last_ok_ts(tmp_path):
    clock = Clock(1000.0)
    x = RaisingFakeX()
    w = _worker(tmp_path, x, now_fn=clock)
    w.poll_once()
    assert w.status()["consecutive_errors"] == 1

    w.x_client = FakeX([])
    result = w.poll_once()
    status = w.status()
    assert result == 0
    assert status["consecutive_errors"] == 0
    assert status["last_ok_ts"] == 1000.0
    assert status["stale"] is False


def test_status_stale_after_window_elapses_since_last_success(tmp_path):
    clock = Clock(1000.0)
    w = _worker(tmp_path, FakeX([]), now_fn=clock, )
    w.stale_after_s = 100.0
    w.poll_once()
    assert w.status()["stale"] is False

    clock.advance(50.0)
    assert w.status()["stale"] is False

    clock.advance(100.0)  # total 150 > 100 window
    assert w.status()["stale"] is True


# ─── run_forever ────────────────────────────────────────────────────────────


def test_run_forever_bounded_by_iterations_uses_interval_when_healthy(tmp_path):
    w = _worker(tmp_path, FakeX([]))
    sleeps = []
    w.run_forever(
        interval_seconds=42.0,
        iterations=3,
        sleep=sleeps.append,
        shutdown_poll_granularity_seconds=10_000.0,
    )
    # 3 polls, 2 inter-poll gaps, each a healthy interval_seconds sleep.
    assert sleeps == [42.0, 42.0]


def test_run_forever_backoff_grows_with_consecutive_errors(tmp_path):
    w = _worker(tmp_path, RaisingFakeX())
    sleeps = []
    w.run_forever(
        interval_seconds=5.0,
        iterations=3,
        sleep=sleeps.append,
        backoff_base=1.0,
        backoff_cap=1000.0,
        shutdown_poll_granularity_seconds=10_000.0,
    )
    # consecutive_errors after poll 1 -> 1 (delay = 1 * 2**1 = 2.0)
    # consecutive_errors after poll 2 -> 2 (delay = 1 * 2**2 = 4.0)
    assert sleeps == [2.0, 4.0]
    assert sleeps[0] < sleeps[1]  # backoff strictly grows with more errors


def test_run_forever_backoff_is_capped(tmp_path):
    w = _worker(tmp_path, RaisingFakeX())
    sleeps = []
    w.run_forever(
        interval_seconds=5.0,
        iterations=5,
        sleep=sleeps.append,
        backoff_base=100.0,
        backoff_cap=250.0,
        shutdown_poll_granularity_seconds=10_000.0,
    )
    assert max(sleeps) <= 250.0
    assert sleeps[-1] == 250.0


def test_run_forever_resets_to_interval_after_recovery(tmp_path):
    x = RaisingFakeX()
    w = _worker(tmp_path, x)
    calls = {"n": 0}

    def flaky_search(query, since_id=None):
        calls["n"] += 1
        if calls["n"] <= 1:
            # Only the very first search_recent call (poll 1's mention
            # query) fails; every call from poll 2 onward succeeds.
            raise XClientError("X API 503: service unavailable")
        return []

    x.search_recent = flaky_search

    sleeps = []
    w.run_forever(
        interval_seconds=9.0,
        iterations=3,
        sleep=sleeps.append,
        backoff_base=1.0,
        backoff_cap=1000.0,
        shutdown_poll_granularity_seconds=10_000.0,
    )
    # Poll 1 fails (consecutive_errors=1 -> delay base*2**1 = 2.0). Poll 2's
    # searches all succeed -> consecutive_errors resets to 0 -> delay goes
    # back to the plain interval_seconds.
    assert sleeps[0] == 2.0
    assert sleeps[1] == 9.0  # recovered -> back to plain interval


def test_run_forever_stops_promptly_when_stop_requested_mid_sleep(tmp_path):
    w = _worker(tmp_path, FakeX([]))
    polls = {"n": 0}
    orig_poll_once = w.poll_once

    def counting_poll_once():
        polls["n"] += 1
        return orig_poll_once()

    w.poll_once = counting_poll_once

    sleep_calls = {"n": 0}
    flip_at_chunk = 3

    def fake_sleep(secs):
        sleep_calls["n"] += 1

    stop = {"flag": False}

    def should_stop():
        if sleep_calls["n"] >= flip_at_chunk:
            stop["flag"] = True
        return stop["flag"]

    w.run_forever(
        interval_seconds=60.0,
        sleep=fake_sleep,
        stop_requested=should_stop,
        shutdown_poll_granularity_seconds=1.0,
    )

    assert polls["n"] == 1
    assert sleep_calls["n"] == flip_at_chunk
