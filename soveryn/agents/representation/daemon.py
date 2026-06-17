"""Representation daemon process loop.

Spin-bug-resistant tick loop mirroring soveryn/agents/dream/daemon.py.
SIGTERM/SIGINT triggers graceful shutdown.

Constructor accepts injected conv_store, lattice_store, chat_fn, embed_fn,
and config — no module-level DB connections — so tests can drive _do_tick
with fakes and zero HTTP / real model calls.

Run as: `python -m soveryn.agents.representation`.
"""
from __future__ import annotations

import json
import logging
import signal
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from soveryn.agents.representation.briefing import build_briefing
from soveryn.agents.representation.cognition import run_representation_pass
from soveryn.agents.representation.config import RepresentationConfig
from soveryn.agents.representation.trigger import evaluate
from soveryn.agents.representation.writeback import write_conclusions
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.lattice.legacy import LatticeStore

logger = logging.getLogger(__name__)

# How far back to scan when _last_run_at is None (first ever run).
_FIRST_RUN_LOOKBACK_HOURS = 72

# Autonomous session title prefixes to exclude from turn counts (same list
# as in briefing.py / dream daemon).
_AUTONOMOUS_PREFIXES = ("⚙️", "🤖", "[daemon]", "[ares]", "[signal]",
                        "[heartbeat]", "[signal]", "[patrol]", "[webhook]")


def _is_autonomous_title(title: str | None) -> bool:
    if not title:
        return False
    lower = title.lower()
    return any(lower.startswith(p.lower()) for p in _AUTONOMOUS_PREFIXES)


class RepresentationDaemon:
    """Single-threaded tick loop for the representation pass.

    Mirrors DreamDaemon shape: spin-bug-resistant sleep math, SIGTERM/SIGINT
    handling, injectable deps for clean unit testing.
    """

    def __init__(
        self,
        *,
        conv_store: ConversationStore,
        lattice_store: LatticeStore,
        chat_fn: Callable[[str, str], str] | None,
        embed_fn: Callable[[str], tuple[float, ...]] | None,
        config: RepresentationConfig,
        dryrun_log_path: Path | None = None,
    ) -> None:
        self.conv_store = conv_store
        self.lattice_store = lattice_store
        self.chat_fn = chat_fn
        self.embed_fn = embed_fn
        self.config = config
        # Structured review artifact (one JSONL line per tick with conclusions).
        # None in tests → no file side effect. __main__ wires the real path.
        self.dryrun_log_path = dryrun_log_path
        self._stop = False
        # Advances to `now` on every eligible tick. None = never run.
        self._last_run_at: datetime | None = None

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        logger.info(
            "representation daemon starting. config=%s", self.config
        )
        # Spin-bug-resistant sleep math (mirrors dream daemon 0fb715b pattern):
        # _last_run_at advances only on eligible ticks.
        # last_tick_at advances EVERY tick so sleep_target never drifts into
        # the past on consecutive skipped ticks.
        last_tick_at: datetime | None = None
        while not self._stop:
            now = datetime.now()
            try:
                self._do_tick(now=now)
            except Exception:
                logger.exception("representation tick failed")
            last_tick_at = now  # always advance — the spin-bug fix
            sleep_target = last_tick_at + timedelta(
                seconds=self.config.tick_interval_seconds
            )
            while not self._stop and datetime.now() < sleep_target:
                time.sleep(
                    min(0.5, max(0.05, (sleep_target - datetime.now()).total_seconds()))
                )
        logger.info("representation daemon stopped cleanly")

    def _handle_signal(self, *_: Any) -> None:
        logger.info("representation daemon received shutdown signal")
        self._stop = True

    # ─── Per-tick work ──────────────────────────────────────────────────────

    def _do_tick(self, *, now: datetime) -> dict:
        """Execute one daemon tick. Returns a summary dict.

        `now` is injected (never calls datetime.now() internally) so tests
        can drive exact timestamps without patching.

        Summary keys:
            eligible       — bool
            skip_reason    — str | None
            conclusion_count — int (0 when ineligible or empty)
            written        — dict from write_conclusions (dry_run fields, etc.)
        """
        new_turn_count = self._count_new_turns_since(self._last_run_at, now)
        eligibility = evaluate(new_turn_count, self.config)

        if not eligibility.eligible:
            logger.debug(
                "representation tick skipped: %s (new_turns=%d)",
                eligibility.skip_reason, new_turn_count,
            )
            return {
                "eligible": False,
                "skip_reason": eligibility.skip_reason,
                "conclusion_count": 0,
                "written": None,
            }

        run_id = str(uuid.uuid4())
        logger.info(
            "representation tick %s starting. new_turns=%d dry_run=%s",
            run_id, new_turn_count, self.config.dry_run,
        )

        briefing_text, prior_text, source_ids = build_briefing(
            self.conv_store,
            self.lattice_store,
            owner_agent=self.config.owner_agent,
            subject=self.config.subject,
            turns_per_briefing=self.config.turns_per_briefing,
        )

        conclusions = run_representation_pass(
            subject=self.config.subject,
            briefing=briefing_text,
            prior_conclusions=prior_text,
            cognition_url=self.config.cognition_url,
            chat_fn=self.chat_fn,
        )

        # Review artifact — record what this tick concluded (the dry-run log
        # Vett + Aetheria inspect) BEFORE writeback, so it's captured whether
        # or not writes are live.
        self._record_dryrun(run_id=run_id, now=now, conclusions=conclusions)

        written = write_conclusions(
            self.lattice_store,
            conclusions,
            owner_agent=self.config.owner_agent,
            subject=self.config.subject,
            run_id=run_id,
            embed_fn=self.embed_fn,
            dry_run=self.config.dry_run,
            supersedes=None,  # P3 — not yet implemented
        )

        # Advance the last-run cursor ONLY on eligible ticks
        self._last_run_at = now

        logger.info(
            "representation tick %s done. conclusions=%d written=%s",
            run_id, len(conclusions), written,
        )

        return {
            "eligible": True,
            "skip_reason": None,
            "conclusion_count": len(conclusions),
            "written": written,
        }

    def _record_dryrun(self, *, run_id: str, now: datetime, conclusions: list) -> None:
        """The dry-run review artifact for Vett/Aetheria: log each would-write
        conclusion at INFO, and (if a path is set) append one JSONL line per
        tick. Best-effort — never crashes the tick."""
        for c in conclusions:
            logger.info(
                "representation would-write [%s | %s] %s :: premises=%s",
                c.mode, c.confidence, c.content, list(c.premises),
            )
        if not self.dryrun_log_path or not conclusions:
            return
        try:
            record = {
                "ts": now.isoformat(),
                "run_id": run_id,
                "dry_run": self.config.dry_run,
                "subject": self.config.subject,
                "conclusions": [
                    {"mode": c.mode, "confidence": c.confidence,
                     "content": c.content, "premises": list(c.premises)}
                    for c in conclusions
                ],
            }
            self.dryrun_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.dryrun_log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception:
            logger.exception("representation: failed to append dry-run artifact")

    # ─── State queries (via injected stores) ────────────────────────────────

    def _count_new_turns_since(
        self, since: datetime | None, now: datetime
    ) -> int:
        """Count user+assistant turns for owner_agent in non-autonomous
        sessions since `since` (or a wide lookback window when None).

        Uses conv_store's public API (list_sessions + load_history) so the
        count works in tests with a real ConversationStore on tmp_path — no
        direct SQLite needed.
        """
        if since is None:
            since_dt = now - timedelta(hours=_FIRST_RUN_LOOKBACK_HOURS)
        else:
            since_dt = since

        try:
            sessions = self.conv_store.list_sessions_with_recent_activity(
                agent=self.config.owner_agent,
                since=since_dt,
                exclude_session_id="",  # never exclude anything
            )
        except Exception:
            logger.exception("representation: failed to list sessions for turn count")
            return 0

        total = 0
        for session in sessions:
            if _is_autonomous_title(session.title):
                continue
            try:
                history = self.conv_store.load_history(session.session_id)
            except Exception:
                logger.exception(
                    "representation: failed to load history session=%s", session.session_id
                )
                continue
            for turn in history:
                if turn.role not in ("user", "assistant"):
                    continue
                # Only count turns timestamped AFTER the cutoff.
                # Turn.timestamp is an isoformat string; compare lexicographically.
                if since is not None and turn.timestamp <= since_dt.isoformat():
                    continue
                total += 1

        return total
