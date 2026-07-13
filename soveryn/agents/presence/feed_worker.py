"""XFeedWorker — isolated, dumb feed poll loop for the Aetheria X presence build.

Searches X for own-handle mentions (kind="mention") first, then each niche
term (kind="topic"), scores every new tweet with `score_tweet`, and stores
any tweet scoring >= `cfg.score_threshold` as a pending `Candidate`.
Deliberately "dumb": no drafting, no LLM call, no posting — just
search -> score -> store. That keeps this worker safe to run standalone,
continuously, well before the real Aetheria loop (which reads its output)
exists.

`XClientError` raised by the injected `x_client` is caught inside
`poll_once` and never propagates — a transient X API outage degrades a
poll to a no-op (0 new candidates) instead of crashing the caller. Repeated
errors are tracked so `run_forever` can back off exponentially instead of
hammering X through an outage, and `status()` exposes a `stale` flag so an
external health check can tell the worker has stopped making progress.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone

from soveryn.agents.presence.candidate_store import Candidate, CandidateStore
from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.scorer import score_tweet
from soveryn.agents.presence.x_client import Tweet, XClient, XClientError

NowFn = Callable[[], float]
Sleep = Callable[[float], None]
StopRequested = Callable[[], bool]

DEFAULT_STALE_AFTER_SECONDS = 900.0


class XFeedWorker:
    """Isolated poll loop: search X, score tweets, store candidates above threshold."""

    agent_name = "x_feed_worker"

    def __init__(
        self,
        *,
        cfg: PresenceConfig,
        x_client: XClient,
        store: CandidateStore,
        now_fn: NowFn,
        stale_after_s: float = DEFAULT_STALE_AFTER_SECONDS,
    ) -> None:
        self.cfg = cfg
        self.x_client = x_client
        self.store = store
        self.now_fn = now_fn
        self.stale_after_s = stale_after_s
        self._last_ok_ts: float | None = None
        self._consecutive_errors = 0
        self._last_error: str | None = None

    def poll_once(self) -> int:
        """Search mentions then niche terms, score, and store new candidates.

        Searches the own-handle mention query FIRST (kind="mention") so a
        tweet that both mentions the handle and matches a niche term is
        stored once, as a mention, with the mention score boost intact —
        the subsequent niche-term pass then skips it via `store.is_seen`.
        Already-seen tweet ids (in `candidates` or `posted_ids`) are skipped
        before scoring; only tweets scoring >= `cfg.score_threshold` are
        upserted.

        Returns the number of NEW candidates upserted this call.

        On `XClientError` from any search call, the error is recorded (see
        `status()`) and this returns 0 WITHOUT raising — a transient X
        outage must degrade this to a no-op, not crash the caller's loop.
        Any candidates already upserted earlier in this same call (from
        searches that succeeded before the failing one) remain stored; only
        the returned count and success bookkeeping reflect the failure.
        """
        try:
            mention_query = f"@{self.cfg.own_handle}"
            new_count = self._ingest(
                self.x_client.search_recent(mention_query), kind="mention", is_mention=True
            )
            for term in self.cfg.niche_terms:
                new_count += self._ingest(
                    self.x_client.search_recent(term), kind="topic", is_mention=False
                )
        except XClientError as exc:
            self._consecutive_errors += 1
            self._last_error = str(exc)
            return 0

        self._consecutive_errors = 0
        self._last_error = None
        self._last_ok_ts = self.now_fn()
        return new_count

    def _ingest(self, tweets: list[Tweet], *, kind: str, is_mention: bool) -> int:
        """Score and store `tweets` from one search, skipping already-seen ids.

        Returns the number of new candidates upserted.
        """
        stored = 0
        for tweet in tweets:
            if self.store.is_seen(tweet.id):
                continue
            # Skip tweets she cannot reply to: an uninvited reply to a
            # conversation whose author restricts replies (to mentioned or
            # followed users only) 403s at post time — "Reply to this
            # conversation is not allowed" — and burns a metered X credit for
            # nothing. Mentions are exempt: being mentioned means the author
            # engaged her, so the reply is allowed regardless of the setting.
            if not is_mention and tweet.reply_settings != "everyone":
                continue
            score = score_tweet(tweet, self.cfg, is_mention=is_mention)
            if score < self.cfg.score_threshold:
                continue
            self.store.upsert(
                Candidate(
                    tweet_id=tweet.id,
                    author=tweet.author,
                    text=tweet.text,
                    url=tweet.url,
                    kind=kind,
                    score=score,
                    status="pending",
                    created_at=datetime.fromtimestamp(self.now_fn(), tz=timezone.utc).isoformat(),
                )
            )
            stored += 1
        return stored

    def status(self) -> dict:
        """Health snapshot for external monitoring (no I/O, pure counters).

        `stale` is True when the worker has never once completed a
        successful poll, or its last success is older than `stale_after_s`
        relative to `now_fn()` — either way, nothing fresh is landing in
        the candidate store.
        """
        now = self.now_fn()
        if self._last_ok_ts is None:
            stale = True
        else:
            stale = (now - self._last_ok_ts) > self.stale_after_s
        return {
            "last_ok_ts": self._last_ok_ts,
            "consecutive_errors": self._consecutive_errors,
            "stale": stale,
        }

    def run_forever(
        self,
        *,
        interval_seconds: float,
        iterations: int | None = None,
        sleep: Sleep = time.sleep,
        stop_requested: StopRequested | None = None,
        shutdown_poll_granularity_seconds: float = 1.0,
        backoff_base: float = 30.0,
        backoff_cap: float = 1800.0,
    ) -> None:
        """Run the poll loop; `iterations` exists so tests can bound it.

        Mirrors `soveryn.agents.ares.daemon.AresDaemonSurface.run_forever`'s
        chunked, interruptible sleep so a SIGTERM-driven `stop_requested`
        flip is observed within ~one granularity instead of at the end of
        the full inter-poll sleep (Python's `time.sleep` is non-interruptible
        per PEP 475).

        Unlike a fixed-interval daemon, the inter-poll sleep is NOT always
        `interval_seconds`: whenever the poll that just ran left
        `consecutive_errors > 0`, the sleep backs off exponentially —
        `min(backoff_cap, backoff_base * 2**consecutive_errors)` — so an X
        API outage is never hammered every `interval_seconds`. The backoff
        resets to `interval_seconds` the moment a poll succeeds.
        """
        should_stop = stop_requested or _never_stop
        completed = 0
        while iterations is None or completed < iterations:
            if should_stop():
                break
            self.poll_once()
            completed += 1
            if iterations is not None and completed >= iterations:
                break
            if should_stop():
                break
            if self._consecutive_errors > 0:
                delay = min(backoff_cap, backoff_base * (2 ** self._consecutive_errors))
            else:
                delay = interval_seconds
            _interruptible_sleep(
                delay,
                should_stop=should_stop,
                sleep=sleep,
                granularity=shutdown_poll_granularity_seconds,
            )


def _never_stop() -> bool:
    return False


def _interruptible_sleep(
    duration_seconds: float,
    *,
    should_stop: StopRequested,
    sleep: Sleep,
    granularity: float = 1.0,
) -> None:
    """Sleep up to `duration_seconds` total, but check `should_stop()`
    every `granularity` seconds and exit early on True. Chunks the call
    to the injected `sleep` so tests can verify both the chunking and
    the early-exit behavior with deterministic fake sleep.
    """
    if duration_seconds <= 0:
        return
    if granularity <= 0:
        granularity = duration_seconds
    elapsed = 0.0
    while elapsed < duration_seconds:
        if should_stop():
            return
        chunk = min(granularity, duration_seconds - elapsed)
        sleep(chunk)
        elapsed += chunk
