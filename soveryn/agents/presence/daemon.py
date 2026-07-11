"""PresenceDaemonSurface — orchestrates the @Soveryn_AI presence loop.

Wires Tasks 1-9 together: search X for niche terms + own-handle mentions,
score and store candidates above threshold, draft the top-ranked ones via an
injected Aetheria draft_fn, and send them to Jon over Signal for approval.
`resolve_reply` classifies his Signal reply and publishes (or rejects) —
nothing reaches X without that human gate. Every resolve outcome is logged to
`signal_log` for later DPO export, and `run_forever` mirrors
`soveryn.agents.ares.daemon.AresDaemonSurface.run_forever` so SIGTERM-driven
shutdown is honored mid-sleep the same way across daemons.

Pending drafts live in an injected `PendingStore` (SQLite), not an in-RAM
dict — the signal bridge that will deliver Jon's `y`/`n`/edit replies runs in
a separate process, and two processes only share state through SQLite.
`drain_pending_replies` pulls queued replies out of that store and resolves
them each loop iteration.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

from soveryn.agents.presence.approval import classify_reply, format_signal_message
from soveryn.agents.presence.candidate_store import Candidate, CandidateStore
from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.drafting import Draft, draft_for_candidate
from soveryn.agents.presence.pending_store import PendingStore
from soveryn.agents.presence.publisher import PublishResult, publish
from soveryn.agents.presence.scorer import score_tweet
from soveryn.agents.presence.signal_log import SignalLog
from soveryn.agents.presence.x_client import Tweet, XClient

logger = logging.getLogger(__name__)

DraftFn = Callable[[str], str]
SendFn = Callable[[str], None]
Sleep = Callable[[float], None]
StopRequested = Callable[[], bool]


class PresenceDaemonSurface:
    """@Soveryn_AI presence daemon: scan → draft → Signal approval → publish."""

    agent_name = "presence"

    def __init__(
        self,
        *,
        cfg: PresenceConfig,
        x_client: XClient,
        store: CandidateStore,
        draft_fn: DraftFn,
        send_fn: SendFn,
        signal_log: SignalLog,
        pending_store: PendingStore,
    ) -> None:
        self.cfg = cfg
        self.x_client = x_client
        self.store = store
        self.draft_fn = draft_fn
        self.send_fn = send_fn
        self.signal_log = signal_log
        self.pending_store = pending_store

    def scan_once(self) -> int:
        """Search + score + upsert candidates, then draft and send the
        top-ranked pending ones over Signal for approval.

        Searches the own-handle mention query (kind="mention", scored with
        the mention boost) BEFORE every niche term (kind="topic"), so a tweet
        that both mentions the handle and matches a niche term is upserted as
        a mention first — the niche pass then skips it via is_seen, keeping
        its reply linkage and mention boost intact. Already-seen tweet ids
        (in candidates or posted_ids) are skipped before scoring. Only
        candidates scoring >= cfg.score_threshold are stored.

        Returns the number of drafts sent this scan (not the number of
        candidates ingested).
        """
        mention_query = f"@{self.cfg.own_handle}"
        self._ingest(self.x_client.search_recent(mention_query), kind="mention", is_mention=True)

        for term in self.cfg.niche_terms:
            self._ingest(self.x_client.search_recent(term), kind="topic", is_mention=False)

        sent = 0
        for candidate in self.store.pending_ranked(self.cfg.max_drafts_per_scan):
            draft = draft_for_candidate(candidate, self.draft_fn)
            if draft is None:
                # Terminal status: a skip must not leave the candidate in
                # "pending", or pending_ranked keeps re-surfacing it on every
                # future scan and it re-runs the model for free forever.
                self.store.mark(candidate.tweet_id, "skipped")
                continue
            # Deterministic draft id — the candidate's own tweet_id, never a
            # wall-clock timestamp or random value (drafts must be
            # reproducible from a scan's inputs alone).
            draft_id = candidate.tweet_id
            self.pending_store.put_draft(draft_id, draft)
            self.store.mark(candidate.tweet_id, "awaiting_approval")
            self.send_fn(format_signal_message(draft, draft_id))
            sent += 1
        return sent

    def _ingest(self, tweets: list[Tweet], *, kind: str, is_mention: bool) -> None:
        """Score and store `tweets` from one search, skipping already-seen ids."""
        for tweet in tweets:
            if self.store.is_seen(tweet.id):
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
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
            )

    def resolve_reply(self, draft_id: str, reply_text: str) -> PublishResult | None:
        """Classify Jon's Signal reply for `draft_id` and act on it.

        approve → publish the draft's own text. edit → publish Jon's literal
        replacement text. reject → mark the candidate "rejected" and publish
        nothing. Every outcome (including reject) is logged to signal_log for
        later DPO export.

        The pending draft is deleted from `self.pending_store` on a
        successful publish (approve/edit with `PublishResult.ok`) or on
        reject. On a FAILED publish, the pending draft is deliberately LEFT
        in the store — so a repeat reply (e.g. Jon retrying "y" after an X
        API hiccup) can resolve the same draft again instead of hitting
        "unknown draft id".
        """
        draft = self.pending_store.get_draft(draft_id)
        if draft is None:
            return None

        action, payload = classify_reply(reply_text)

        if action == "approve":
            result = publish(draft.text, draft, self.x_client, self.store)
            self.signal_log.record(draft_id, "approve", draft.text, draft.text, None)
            if result.ok:
                self.pending_store.delete_draft(draft_id)
            return result

        if action == "edit":
            new_text = payload
            result = publish(new_text, draft, self.x_client, self.store)
            self.signal_log.record(draft_id, "edit", draft.text, new_text, None)
            if result.ok:
                self.pending_store.delete_draft(draft_id)
            return result

        # reject
        self.store.mark(draft.candidate_tweet_id, "rejected")
        self.signal_log.record(draft_id, "reject", draft.text, draft.text, payload)
        self.pending_store.delete_draft(draft_id)
        return None

    def drain_pending_replies(self) -> int:
        """Resolve every reply queued in `pending_store` since the last drain.

        Each reply is resolved independently inside a try/except so one bad
        reply (e.g. a resolve that raises) can't abort the drain of the rest
        of the queue. Returns the number of replies processed (attempted),
        regardless of whether an individual resolve raised.
        """
        processed = 0
        for draft_id, reply_text in self.pending_store.take_replies():
            try:
                self.resolve_reply(draft_id, reply_text)
            except Exception:
                logger.exception(
                    "presence resolve_reply failed for draft_id=%s; continuing",
                    draft_id,
                )
            processed += 1
        return processed

    def run_forever(
        self,
        *,
        interval_seconds: float = 60.0,
        iterations: int | None = None,
        sleep: Sleep = time.sleep,
        stop_requested: StopRequested | None = None,
        shutdown_poll_granularity_seconds: float = 1.0,
    ) -> None:
        """Run the scan loop; `iterations` exists so tests can bound it.

        Each iteration drains any queued Signal replies (cheap, so every
        iteration) before scanning. Sleep between scans is chunked into
        `shutdown_poll_granularity_seconds` slices so a SIGTERM-driven
        `stop_requested` flip is observed within ~one granularity, not at
        end of the full inter-scan sleep. Python 3.5+ sleep is
        non-interruptible (PEP 475 — sleep resumes after signal), so without
        chunking, SIGTERM mid-sleep would wait the full interval.
        """

        should_stop = stop_requested or _never_stop
        completed = 0
        while iterations is None or completed < iterations:
            if should_stop():
                break
            try:
                self.drain_pending_replies()
                self.scan_once()
            except Exception:
                # A transient failure (e.g. an X API error) must not exit
                # the daemon — log it and continue to the next iteration.
                logger.exception("presence loop iteration failed; continuing")
            completed += 1
            if iterations is not None and completed >= iterations:
                break
            if should_stop():
                break
            _interruptible_sleep(
                interval_seconds,
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
