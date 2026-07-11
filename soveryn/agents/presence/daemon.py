"""PresenceDaemonSurface — orchestrates the @Soveryn_AI presence loop.

Wires Tasks 1-9 together: search X for niche terms + own-handle mentions,
score and store candidates above threshold, draft the top-ranked ones via an
injected Aetheria draft_fn, and send them to Jon over Signal for approval.
`resolve_reply` classifies his Signal reply and publishes (or rejects) —
nothing reaches X without that human gate. Every resolve outcome is logged to
`signal_log` for later DPO export, and `run_forever` mirrors
`soveryn.agents.ares.daemon.AresDaemonSurface.run_forever` so SIGTERM-driven
shutdown is honored mid-sleep the same way across daemons.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone

from soveryn.agents.presence.approval import classify_reply, format_signal_message
from soveryn.agents.presence.candidate_store import Candidate, CandidateStore
from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.drafting import Draft, draft_for_candidate
from soveryn.agents.presence.publisher import PublishResult, publish
from soveryn.agents.presence.scorer import score_tweet
from soveryn.agents.presence.signal_log import SignalLog
from soveryn.agents.presence.x_client import Tweet, XClient

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
        pending: dict[str, Draft] | None = None,
    ) -> None:
        self.cfg = cfg
        self.x_client = x_client
        self.store = store
        self.draft_fn = draft_fn
        self.send_fn = send_fn
        self.signal_log = signal_log
        self.pending: dict[str, Draft] = pending if pending is not None else {}

    def scan_once(self) -> int:
        """Search + score + upsert candidates, then draft and send the
        top-ranked pending ones over Signal for approval.

        Searches every niche term (kind="topic") plus one own-handle mention
        query (kind="mention", scored with the mention boost). Already-seen
        tweet ids (in candidates or posted_ids) are skipped before scoring.
        Only candidates scoring >= cfg.score_threshold are stored.

        Returns the number of drafts sent this scan (not the number of
        candidates ingested).
        """
        for term in self.cfg.niche_terms:
            self._ingest(self.x_client.search_recent(term), kind="topic", is_mention=False)

        mention_query = f"@{self.cfg.own_handle}"
        self._ingest(self.x_client.search_recent(mention_query), kind="mention", is_mention=True)

        sent = 0
        for candidate in self.store.pending_ranked(self.cfg.max_drafts_per_scan):
            draft = draft_for_candidate(candidate, self.draft_fn)
            if draft is None:
                continue
            # Deterministic draft id — the candidate's own tweet_id, never a
            # wall-clock timestamp or random value (drafts must be
            # reproducible from a scan's inputs alone).
            draft_id = candidate.tweet_id
            self.pending[draft_id] = draft
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
        later DPO export. The draft is always removed from `self.pending`,
        regardless of outcome, so a resolved draft can't be resolved twice.
        """
        draft = self.pending.pop(draft_id, None)
        if draft is None:
            return None

        action, payload = classify_reply(reply_text)

        if action == "approve":
            result = publish(draft.text, draft, self.x_client, self.store)
            self.signal_log.record(draft_id, "approve", draft.text, draft.text, None)
            return result

        if action == "edit":
            new_text = payload
            result = publish(new_text, draft, self.x_client, self.store)
            self.signal_log.record(draft_id, "edit", draft.text, new_text, None)
            return result

        # reject
        self.store.mark(draft.candidate_tweet_id, "rejected")
        self.signal_log.record(draft_id, "reject", draft.text, draft.text, payload)
        return None

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

        Sleep between scans is chunked into `shutdown_poll_granularity_seconds`
        slices so a SIGTERM-driven `stop_requested` flip is observed within
        ~one granularity, not at end of the full inter-scan sleep. Python 3.5+
        sleep is non-interruptible (PEP 475 — sleep resumes after signal),
        so without chunking, SIGTERM mid-sleep would wait the full interval.
        """

        should_stop = stop_requested or _never_stop
        completed = 0
        while iterations is None or completed < iterations:
            if should_stop():
                break
            self.scan_once()
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
