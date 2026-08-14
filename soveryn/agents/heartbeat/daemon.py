"""Heartbeat daemon process loop.

Separate process from vnext (Ares-style isolation). Talks to vnext over
the standard /chat endpoint. Reads board + lattice + activity state
directly from the lattice and conversations DBs. Records every tick to
heartbeat_log.

Run as a module: `python -m soveryn.agents.heartbeat`.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from soveryn.agents.heartbeat.daily_post import (
    DAILY_POST_INVITE,
    DEFAULT_DAILY_POST_HOUR,
    read_last_invite_date,
    should_nudge,
    write_last_invite_date,
)
from soveryn.agents.heartbeat.date_extract import build_dated_items
from soveryn.agents.heartbeat.delta import compute_delta
from soveryn.agents.heartbeat.materiality import (
    MaterialSignal,
    detect_materiality,
    get_deploy_started_at,
)
from soveryn.agents.heartbeat.prompt import (
    BoardSnapshot,
    LatticeSnapshot,
    build_heartbeat_prompt,
)
from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog
from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.digest import build_digest
from soveryn.agents.heartbeat.trigger import (
    HeartbeatConfig,
    SkipReason,
    TickEligibility,
    evaluate_tick,
)


logger = logging.getLogger(__name__)

# Defaults — overridable via env.
DEFAULT_VNEXT_BASE = "http://127.0.0.1:5001"
DEFAULT_LATTICE_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
DEFAULT_CONV_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"
DEFAULT_SALIENCE_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "salience_vnext.db"
DEFAULT_THOUGHTS_LOG = Path.home() / "soveryn_vnext" / "data" / "heartbeat_thoughts.jsonl"
# Sentinel file for T6 stall amnesty deploy clock.  Written once on first
# heartbeat tick after deploy; subsequent ticks read it to compute
# hours_since_deploy for the amnesty/worst-first logic in detect_materiality.
# Path is gitignored (data/heartbeat_deploy_started_at).
DEFAULT_DEPLOY_SENTINEL = Path.home() / "soveryn_vnext" / "data" / "heartbeat_deploy_started_at"
# Once-per-day AM X-post nudge: persists the last-nudged date so a mid-day
# daemon restart doesn't re-nudge. Path is gitignored (data/).
DEFAULT_DAILY_POST_STATE = Path.home() / "soveryn_vnext" / "data" / "x_daily_post_state.json"

# Window of lattice activity to summarise in the brief (separate from the
# interval/backoff knobs since this is a *content* knob not a *timing* knob).
LATTICE_WINDOW_MINUTES = 60

# A Blueprint is "stalled" if it's been in Refining longer than this without
# moving. Heuristic; tunable.
STALLED_BLUEPRINT_THRESHOLD_MINUTES = 240  # 4 hours

# How long the daemon waits for vnext to return Aetheria's response. Real
# generation can take 30-90s depending on prompt+thinking budget.
CHAT_TIMEOUT_SECONDS = 240


class HeartbeatHTTPError(RuntimeError):
    """An HTTP error from vNext, carrying the response body.

    Exists so the pulse log records WHY the call failed rather than
    just its status code."""

WEBHOOK_SESSION_TITLE_PREFIX = "[webhook]"
HEARTBEAT_SESSION_TITLE = "[heartbeat] aetheria"


class HeartbeatDaemon:
    """Single-threaded tick loop. One tick at a time; if a tick takes longer
    than the interval, the next tick fires when the current one returns."""

    def __init__(
        self,
        config: HeartbeatConfig,
        *,
        vnext_base: str = DEFAULT_VNEXT_BASE,
        lattice_db: Path = DEFAULT_LATTICE_DB,
        conv_db: Path = DEFAULT_CONV_DB,
        salience_db: Path = DEFAULT_SALIENCE_DB,
        deploy_sentinel: Path | None = None,
        thoughts_log_path: Path | None = None,
        daily_post_state_path: Path | None = None,
        daily_post_hour: int = DEFAULT_DAILY_POST_HOUR,
        active_context_db: Path | None = None,
        citizens_db: Path | None = None,
    ) -> None:
        self.config = config
        # Citizens commissions registry (charter §12.5). None disables the
        # bookkeeping entirely and the pulse is unaffected — same posture as
        # active_context above. record_pulse also swallows its own failures, so
        # this is belt as well as braces: nothing about writing a commission row
        # is allowed to cost her a heartbeat.
        self._citizens_db = citizens_db
        # Cross-rail live thread. The daemon runs OUT OF PROCESS from the Flask
        # app, so it opens the same SQLite file rather than sharing an object —
        # which is exactly why the store was made connection-per-operation and
        # WAL. None disables the write (tests, and any deployment that has not
        # wired it) without touching the pulse.
        self._active_context = None
        if active_context_db is not None:
            try:
                from soveryn.context.service import ActiveContextService
                from soveryn.context.store import ActiveContextStore
                self._active_context = ActiveContextService(
                    ActiveContextStore(active_context_db)
                )
            except Exception:
                logger.exception("active context unavailable; pulses will not carry")
        self.vnext_base = vnext_base.rstrip("/")
        self.lattice_db = Path(lattice_db)
        self.conv_db = Path(conv_db)
        self.salience_db = Path(salience_db)
        # T6 stall amnesty: sentinel file path for deploy clock.
        # Defaults to DEFAULT_DEPLOY_SENTINEL (data/heartbeat_deploy_started_at)
        # when None; injectable for test isolation (pass tmp_path / "...").
        self.deploy_sentinel: Path = (
            Path(deploy_sentinel) if deploy_sentinel is not None
            else DEFAULT_DEPLOY_SENTINEL
        )
        # T7 thoughts-log: append-only JSONL pulse record. Injectable for test
        # isolation; defaults to DEFAULT_THOUGHTS_LOG in production.
        _tlog_path = (
            Path(thoughts_log_path) if thoughts_log_path is not None
            else DEFAULT_THOUGHTS_LOG
        )
        self._thoughts_log = ThoughtsLog(_tlog_path)
        # Once-per-day AM X-post nudge state. Injectable for test isolation;
        # defaults to DEFAULT_DAILY_POST_STATE in production.
        self.daily_post_state_path: Path = (
            Path(daily_post_state_path) if daily_post_state_path is not None
            else DEFAULT_DAILY_POST_STATE
        )
        self.daily_post_hour = daily_post_hour
        self._stop = False
        self._heartbeat_session_id: str | None = None
        # Idempotent migration: add surfaced_to_chat column to heartbeat_log
        # if missing. Pre-existing DBs (rows from before 2026-06-15) won't
        # have it. Follows the same pattern as legacy.py's dream_log.dry_run
        # column-add — SQLite doesn't support IF NOT EXISTS on ADD COLUMN.
        self._ensure_surfaced_to_chat_column()

    def _ensure_surfaced_to_chat_column(self) -> None:
        """Idempotent column-add for heartbeat_log.surfaced_to_chat.

        Best-effort. The heartbeat_log table itself is created by
        LatticeStore._init_schema, which runs at vnext startup; if vnext
        hasn't started yet the table won't exist and PRAGMA returns empty.
        We catch the OperationalError and skip — the next daemon launch
        after vnext is up will retry.
        """
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                cols = {
                    row[1]
                    for row in con.execute("PRAGMA table_info(heartbeat_log)").fetchall()
                }
                if not cols:
                    # Table doesn't exist yet — vnext hasn't run its lattice
                    # schema init. Nothing to migrate; future tick will see it.
                    return
                if "surfaced_to_chat" not in cols:
                    con.execute(
                        "ALTER TABLE heartbeat_log "
                        "ADD COLUMN surfaced_to_chat INTEGER NOT NULL DEFAULT 0"
                    )
                    logger.info("heartbeat_log migrated: added surfaced_to_chat column")
        except sqlite3.OperationalError:
            logger.warning(
                "heartbeat_log.surfaced_to_chat migration failed; "
                "will retry on next daemon launch",
                exc_info=True,
            )

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def run(self) -> None:
        """Block forever, ticking on the configured cadence. SIGTERM/SIGINT
        triggers graceful shutdown."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        logger.info(
            "heartbeat daemon starting. config=%s vnext=%s",
            self.config, self.vnext_base,
        )
        # `last_heartbeat_at` (eligible-only) is what the interval gate uses
        # in evaluate_tick. `last_tick_at` is what the SLEEP math uses to
        # decide when to next consider a tick. We advance last_tick_at on
        # EVERY tick — eligible or skipped — so consecutive skipped ticks
        # don't leave sleep_target stuck in the past and spin (which the
        # 2026-06-02 dry-run bake surfaced as 628k backoff rows in 68 min).
        last_heartbeat_at = self._latest_heartbeat_completed_at()
        last_tick_at: datetime | None = None
        previous_skip_reason: str | None = None
        while not self._stop:
            now = datetime.now()
            last_activity_at = self._latest_aetheria_activity_at()
            eligibility = evaluate_tick(
                self.config,
                now=now,
                last_heartbeat_at=last_heartbeat_at,
                last_aetheria_activity_at=last_activity_at,
            )
            # Boundary logging: emit ONE info line on transition into or out
            # of QUIET_HOURS so an operator can verify the quiet window opened
            # / closed without grepping every tick row in the DB. 2026-06-07
            # fix: the 48h-of-templated-silence diagnosis would have been
            # 30 seconds instead of 30 minutes if these boundaries had logs.
            current_skip = (
                eligibility.skip_reason.value
                if eligibility.skip_reason is not None
                else None
            )
            if current_skip != previous_skip_reason:
                if current_skip == "quiet_hours":
                    logger.info(
                        "heartbeat entering quiet hours (config: %s) at %s",
                        self.config.quiet_hours, now.isoformat(),
                    )
                elif previous_skip_reason == "quiet_hours":
                    logger.info(
                        "heartbeat exiting quiet hours at %s; "
                        "next eligible state: %s",
                        now.isoformat(),
                        "eligible" if eligibility.eligible else current_skip,
                    )
                previous_skip_reason = current_skip
            self._do_tick(now=now, eligibility=eligibility)
            if eligibility.eligible:
                last_heartbeat_at = now
            last_tick_at = now  # always advance — the bug fix
            # Sleep until the next interval boundary OR until shutdown.
            # Use shorter sleeps so SIGTERM is responsive.
            sleep_target = last_tick_at + timedelta(
                seconds=self.config.interval_seconds
            )
            while not self._stop and datetime.now() < sleep_target:
                time.sleep(min(5.0, max(0.1, (sleep_target - datetime.now()).total_seconds())))
        logger.info("heartbeat daemon stopped cleanly")

    def _handle_signal(self, *_: Any) -> None:
        logger.info("heartbeat daemon received shutdown signal")
        self._stop = True

    # ─── Per-tick work ──────────────────────────────────────────────────────

    def _do_tick(self, *, now: datetime, eligibility: TickEligibility) -> None:
        """Run one tick, recorded as a commission when it is a real pulse.

        Charter §12.5. The commission is BOOKKEEPING, not control: it does not
        decide whether she acts, when she acts, or what she says. It writes down
        that a pulse happened and how it ended, so `on_duty` is derivable and a
        daemon that dies mid-pulse leaves a findable row instead of silence.

        record_pulse never raises on its own — a missing, locked or corrupt
        registry logs and the tick proceeds. A monitoring layer that can silence
        her is worse than none, and this one wraps her spontaneous initiation.
        """
        if not eligibility.eligible:
            # A skipped tick is not work, so it is not a commission.
            self._tick_body(now=now, eligibility=eligibility)
            return

        try:
            from soveryn.citizens.pulse import record_pulse
        except ImportError:
            # pulse.py missing on this install — still run the tick unrecorded.
            # test_repo_integrity is the check that catches the untracked file.
            logger.exception(
                "citizens pulse bookkeeping unavailable; tick proceeds unrecorded"
            )
            self._tick_body(now=now, eligibility=eligibility)
            return
        with record_pulse(
            self._citizens_db,
            "aetheria",
            "heartbeat pulse",
            worker="heartbeat",
            now=now.isoformat(),
        ):
            self._tick_body(now=now, eligibility=eligibility)

    def _tick_body(self, *, now: datetime, eligibility: TickEligibility) -> None:
        tick_id = str(uuid.uuid4())
        triggered_at = now.isoformat()
        if not eligibility.eligible:
            # Skipped tick — log and return.
            self._write_log_row(
                tick_id=tick_id,
                triggered_at=triggered_at,
                completed_at=now.isoformat(),
                eligible=False,
                skip_reason=eligibility.skip_reason.value if eligibility.skip_reason else None,
                action_taken=None,
                tool_call_count=None,
                response_length=None,
                error=None,
            )
            return

        # Eligible — build the brief and invoke (unless dry-run).
        try:
            board = self._gather_board_snapshot(now)
            lattice = self._gather_lattice_snapshot(now)
            last_heartbeat = self._latest_heartbeat_completed_at()
            minutes_since = None
            if last_heartbeat is not None:
                minutes_since = int(
                    (now - last_heartbeat).total_seconds() // 60
                )
            # Salience digest — decay old, read pending, render. Best-effort:
            # _gather_salience swallows its own errors. The outer try/except
            # below still wraps it for defense-in-depth. since fallback covers
            # the daemon's first tick where there's no prior heartbeat row.
            since_for_salience = last_heartbeat or (now - timedelta(days=1))
            salience_section = _gather_salience(
                self.salience_db, since=since_for_salience,
            )
            # T7: gather material signals + compute delta vs prior pulse.
            material_signals = self._gather_material_signals(now)
            # Build the current snapshot for delta framing (shape documented
            # in delta.py module docstring — board counts + material_signals
            # + lattice).  This dict is also persisted in the thoughts-log
            # record so compute_delta can read it as prev_snapshot next pulse
            # (load-bearing contract: don't drop the "snapshot" key from the
            # ThoughtsLog record below).
            current_snapshot: dict = {
                "board": {
                    "open_signal_count": board.open_signal_count,
                    "open_blueprint_count": board.open_blueprint_count,
                    "ready_blueprint_count": board.ready_blueprint_count,
                    "open_friction_count": board.open_friction_count,
                    "stalled_blueprint_count": board.stalled_blueprint_count,
                    "blocked_blueprint_count": board.blocked_blueprint_count,
                    "oldest_open_signal_age_minutes": board.oldest_open_signal_age_minutes,
                    "oldest_open_blueprint_title": board.oldest_open_blueprint_title,
                    "oldest_open_blueprint_age_hours": board.oldest_open_blueprint_age_hours,
                },
                "material_signals": [
                    {"kind": s.kind, "ref": s.ref, "detail": s.detail}
                    for s in material_signals
                ],
                "lattice": {
                    "new_node_count_recent_window": lattice.new_node_count_recent_window,
                    "recent_window_minutes": lattice.recent_window_minutes,
                    "new_contradiction_flag_count": lattice.new_contradiction_flag_count,
                },
            }
            prev_record = self._thoughts_log.last()
            delta = compute_delta(current_snapshot, prev_record)
            # X digest — best-effort. Reads the same feed candidate_store the
            # read_x tool reads; a feed problem (missing db, corrupt store,
            # etc.) must never break the heartbeat tick.
            try:
                x_digest = build_digest(
                    CandidateStore(PresenceConfig.default().db_path)
                ) or ""
            except Exception:
                logger.exception("heartbeat tick: X digest build failed, omitting")
                x_digest = ""
            # Once-per-day AM post nudge — best-effort. Fires on the FIRST
            # eligible tick each calendar day at/after `daily_post_hour` local
            # (`now` is the single wall-clock read passed down from run()), then
            # persists today's date so a mid-day restart won't re-nudge. Any
            # failure here must never break the tick.
            daily_post_invite = ""
            try:
                last_invite = read_last_invite_date(self.daily_post_state_path)
                if should_nudge(
                    now=now,
                    last_invite_date=last_invite,
                    hour_threshold=self.daily_post_hour,
                ):
                    daily_post_invite = DAILY_POST_INVITE
                    write_last_invite_date(
                        self.daily_post_state_path, now.date().isoformat()
                    )
            except Exception:
                logger.exception("heartbeat tick: daily post nudge failed, omitting")
                daily_post_invite = ""
            prompt = build_heartbeat_prompt(
                minutes_since_last_heartbeat=minutes_since,
                board=board,
                lattice=lattice,
                salience_section=salience_section,
                material_signals=material_signals,
                delta=delta,
                x_digest=x_digest,
                daily_post_invite=daily_post_invite,
            )
        except Exception as e:
            logger.exception("heartbeat tick failed during context gathering")
            self._write_log_row(
                tick_id=tick_id,
                triggered_at=triggered_at,
                completed_at=datetime.now().isoformat(),
                eligible=True,
                skip_reason=None,
                action_taken=None,
                tool_call_count=None,
                response_length=None,
                error=f"{type(e).__name__}: {e}",
            )
            return

        if self.config.dry_run:
            logger.info(
                "heartbeat tick %s DRY-RUN. prompt (head): %r",
                tick_id, prompt[:300],
            )
            self._write_log_row(
                tick_id=tick_id,
                triggered_at=triggered_at,
                completed_at=datetime.now().isoformat(),
                eligible=True,
                skip_reason=None,
                action_taken=None,    # dry-run never invokes
                tool_call_count=None,
                response_length=len(prompt),  # log prompt size as a sanity check
                error=None,
            )
            return

        # Live: invoke Aetheria via /chat with the durable heartbeat session.
        # The /chat round-trip persists BOTH this prompt and her assistant note
        # into the durable [heartbeat] aetheria session — that session IS the
        # pulse's home (the "Heartbeat" rail). Her note lands there and nowhere
        # else: we do NOT copy it into any "primary"/main chat. A pure-quiet
        # pulse (empty note) leaves nothing. Material signals stay visible on
        # the Mission Control tile regardless.
        try:
            session_id = self._ensure_heartbeat_session()
            response = self._call_vnext_chat(session_id, prompt)
            action_taken, tool_call_count = self._summarise_response(response)
            response_text = response.get("content", "") if isinstance(response, dict) else ""

            # Her whole response is her note; it already persists in the
            # [heartbeat] session via the /chat round-trip above.
            note = (response_text or "").strip()

            # Memory Grades PR3: dual-write. Full note stays in thoughts log +
            # [heartbeat] session (process/self preserved). Lattice gets only a
            # dense reflection head so always-on writers do not re-bloat essays
            # as the default self-model. Best-effort: never break the pulse.
            if note:
                try:
                    try:
                        from soveryn.platform.lattice.distill import distill_for_lattice
                    except ImportError:
                        # distill module on-disk-only would crash the pulse —
                        # fall back to a hard head so the tick still completes.
                        logger.exception(
                            "heartbeat tick %s: distill module missing; "
                            "using hard truncation", tick_id,
                        )
                        def distill_for_lattice(node_type, text, **kw):  # type: ignore
                            t = (text or "").strip()
                            return t if len(t) <= 500 else t[:499].rstrip() + "…"
                    from soveryn.platform.lattice.legacy import LatticeStore, embed_text
                    head = distill_for_lattice("reflection", note)
                    if head:
                        LatticeStore(self.lattice_db).write_node(
                            agent="aetheria",
                            content=head,
                            node_type="reflection",
                            layer="private",
                            tags=("heartbeat", "reflection", "grade:journal"),
                            embedding=tuple(embed_text(head)),
                            on_overflow="clamp",
                            provenance={
                                "cls": "witnessed",
                                "source": "heartbeat",
                                "pulse_id": tick_id,
                                "ts": now.isoformat(),
                                "grade": "journal",
                                "full_text_ref": f"thoughts_log:pulse_id={tick_id}",
                                "original_chars": len(note),
                            },
                        )
                except Exception:
                    logger.exception(
                        "heartbeat tick %s: lattice private-node write failed "
                        "(best-effort; pulse continues)", tick_id)

            # T7: append a ThoughtsLog record every pulse.
            # The "snapshot" key is LOAD-BEARING — compute_delta reads
            # prev_record["snapshot"] on the next pulse. Do not rename or drop it.
            try:
                _tlog_record: dict = {
                    "pulse_id": tick_id,
                    "ts": now.isoformat(),
                    "snapshot": current_snapshot,          # LOAD-BEARING: compute_delta reads this
                    "material_signals": [
                        {"kind": s.kind, "ref": s.ref, "detail": s.detail}
                        for s in material_signals
                    ],
                    "delta": delta,
                    "note": note,
                    "tool_calls": tool_call_count,
                    # Surfacing to a "primary" chat was removed: pulse notes live
                    # only in the [heartbeat] session, so this is always False.
                    "surfaced": False,
                }
                self._thoughts_log.append(_tlog_record)
                # Carry the CONCLUSION across rails. Before 2026-07-28 the
                # comment above was literally true — notes lived only in the
                # [heartbeat] session and reached nobody, including her. The
                # note replaces the previous one rather than accumulating: 26
                # wakes a day at ~344 tokens cannot ride in a 1500-token brief,
                # and a later pulse supersedes an earlier one anyway.
                if self._active_context is not None and (note or "").strip():
                    try:
                        self._active_context.record_thought(
                            rail="heartbeat", note=note
                        )
                    except Exception:
                        logger.exception(
                            "heartbeat tick %s: active-context write failed; "
                            "pulse unaffected", tick_id,
                        )
            except Exception:
                logger.exception(
                    "heartbeat tick %s: thoughts-log write failed; "
                    "continuing (best-effort)", tick_id,
                )

            self._write_log_row(
                tick_id=tick_id,
                triggered_at=triggered_at,
                completed_at=datetime.now().isoformat(),
                eligible=True,
                skip_reason=None,
                action_taken=action_taken,
                tool_call_count=tool_call_count,
                response_length=len(response_text),
                error=None,
            )
            logger.info(
                "heartbeat tick %s done. action_taken=%s tool_calls=%s "
                "response_len=%d note_len=%d",
                tick_id, action_taken, tool_call_count,
                len(response_text), len(note),
            )
        except Exception as e:
            logger.exception("heartbeat tick failed during chat invocation")
            self._write_log_row(
                tick_id=tick_id,
                triggered_at=triggered_at,
                completed_at=datetime.now().isoformat(),
                eligible=True,
                skip_reason=None,
                action_taken=None,
                tool_call_count=None,
                response_length=None,
                error=f"{type(e).__name__}: {e}",
            )

    # ─── State queries (DB-direct) ──────────────────────────────────────────

    def _latest_heartbeat_completed_at(self) -> datetime | None:
        with sqlite3.connect(str(self.lattice_db)) as con:
            row = con.execute(
                "SELECT completed_at FROM heartbeat_log "
                "WHERE completed_at IS NOT NULL "
                "ORDER BY triggered_at DESC LIMIT 1"
            ).fetchone()
        if row is None or row[0] is None:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except ValueError:
            return None

    def _latest_aetheria_activity_at(self) -> datetime | None:
        """Most recent updated_at across ALL Aetheria sessions — user chat AND
        webhook sessions, BUT explicitly excluding the heartbeat session itself
        (we don't backoff against our own previous tick — that's the interval
        gate's job)."""
        with sqlite3.connect(str(self.conv_db)) as con:
            row = con.execute(
                "SELECT MAX(updated_at) FROM conversation_meta "
                "WHERE agent = 'aetheria' "
                "AND (title IS NULL OR title != ?)",
                (HEARTBEAT_SESSION_TITLE,),
            ).fetchone()
        if row is None or row[0] is None:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except ValueError:
            return None

    def _gather_board_snapshot(self, now: datetime) -> BoardSnapshot:
        with sqlite3.connect(str(self.lattice_db)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT id, content, created_at, provenance FROM nodes "
                "WHERE type = 'coordination'"
            ).fetchall()
        open_signal = 0
        oldest_open_signal_minutes: int | None = None
        open_blueprint = 0
        ready_blueprint = 0
        stalled_blueprint = 0
        blocked_blueprint = 0
        open_friction = 0
        # Track the oldest Open Blueprint by name + age so the prompt can
        # surface the specific commitment instead of just a count. Refining
        # is excluded — stalled_blueprint_count already names that lane.
        oldest_open_blueprint_title: str | None = None
        oldest_open_blueprint_age_minutes: int | None = None
        # We need blocked status — query blockers per Blueprint. To avoid N+1,
        # build a set of all blueprint_ids currently blocked.
        currently_blocked: set[str] = set()
        for r in rows:
            prov = json.loads(r["provenance"] or "{}")
            board = prov.get("board")
            status = prov.get("status")
            if status == "Archived":
                continue
            if board == "Friction" and status != "Archived":
                blocks = prov.get("blocks") or []
                for bp in blocks:
                    currently_blocked.add(bp)
        for r in rows:
            prov = json.loads(r["provenance"] or "{}")
            board = prov.get("board")
            status = prov.get("status")
            if status == "Archived":
                continue
            if board == "Signal" and status == "Open":
                open_signal += 1
                try:
                    age_minutes = int(
                        (now - datetime.fromisoformat(r["created_at"])).total_seconds() // 60
                    )
                    if oldest_open_signal_minutes is None or age_minutes > oldest_open_signal_minutes:
                        oldest_open_signal_minutes = age_minutes
                except (ValueError, TypeError):
                    pass
            elif board == "Blueprint":
                if status == "Open":
                    open_blueprint += 1
                    try:
                        age_minutes = int(
                            (now - datetime.fromisoformat(r["created_at"])).total_seconds() // 60
                        )
                        if (
                            oldest_open_blueprint_age_minutes is None
                            or age_minutes > oldest_open_blueprint_age_minutes
                        ):
                            oldest_open_blueprint_age_minutes = age_minutes
                            # First line of content is the title; bound to a
                            # reasonable length so the prompt stays readable.
                            first_line = (r["content"] or "").split("\n", 1)[0]
                            oldest_open_blueprint_title = first_line[:120]
                    except (ValueError, TypeError):
                        pass
                elif status == "Refining":
                    open_blueprint += 1
                    # Stall check
                    try:
                        age_minutes = int(
                            (now - datetime.fromisoformat(r["created_at"])).total_seconds() // 60
                        )
                        if age_minutes >= STALLED_BLUEPRINT_THRESHOLD_MINUTES:
                            stalled_blueprint += 1
                    except (ValueError, TypeError):
                        pass
                elif status == "Ready":
                    ready_blueprint += 1
                if r["id"] in currently_blocked:
                    blocked_blueprint += 1
            elif board == "Friction" and status != "Archived":
                open_friction += 1
        oldest_open_blueprint_age_hours = (
            oldest_open_blueprint_age_minutes // 60
            if oldest_open_blueprint_age_minutes is not None
            else None
        )
        return BoardSnapshot(
            open_signal_count=open_signal,
            open_blueprint_count=open_blueprint,
            ready_blueprint_count=ready_blueprint,
            open_friction_count=open_friction,
            stalled_blueprint_count=stalled_blueprint,
            blocked_blueprint_count=blocked_blueprint,
            oldest_open_signal_age_minutes=oldest_open_signal_minutes,
            oldest_open_blueprint_title=oldest_open_blueprint_title,
            oldest_open_blueprint_age_hours=oldest_open_blueprint_age_hours,
        )

    def _gather_lattice_snapshot(self, now: datetime) -> LatticeSnapshot:
        window_start = (now - timedelta(minutes=LATTICE_WINDOW_MINUTES)).isoformat()
        with sqlite3.connect(str(self.lattice_db)) as con:
            new_nodes = con.execute(
                "SELECT COUNT(*) FROM nodes WHERE created_at >= ? "
                "AND type NOT IN ('coordination', 'lesson_learned')",
                (window_start,),
            ).fetchone()[0]
            # contradiction_flags came in via the consolidation migration —
            # it's present in production but absent in fresh standalone
            # LatticeStore instances (the migration script writes it, not the
            # base schema). Treat absence as zero contradictions rather than
            # failing the snapshot.
            try:
                contradictions = con.execute(
                    "SELECT COUNT(*) FROM contradiction_flags WHERE flagged_at >= ?",
                    (window_start,),
                ).fetchone()[0]
            except sqlite3.OperationalError:
                contradictions = 0
        return LatticeSnapshot(
            new_node_count_recent_window=int(new_nodes),
            recent_window_minutes=LATTICE_WINDOW_MINUTES,
            new_contradiction_flag_count=int(contradictions),
        )

    def _gather_material_signals(self, now: datetime) -> list[MaterialSignal]:
        """Query real data sources and call detect_materiality.

        Best-effort: any per-source exception is swallowed and logged so a
        transient DB error never kills the heartbeat tick. Returns [] on
        total failure.

        DATA SOURCE STATUS (as of 2026-06-28 schema audit):
          deadline items: [] — NO queryable source. The `nodes` schema and
            coordination provenance JSON have no deadline/date field (only
            created_at/updated_at). Task 5 needs to add a date field or find
            an alternative source before this lane can produce real signals.
          error items:    [] — NO clean queryable source. `fact` nodes contain
            some error-adjacent text (Jon's inbox relays), but these are NOT
            actionable system failures. `vett_patrol_state.last_error` exists
            but is empty in production. `coord_event_log` has no error-kind
            events. Task 5 should consider vett_patrol_state.last_error as the
            real hook once Vett is actively patrolling.
          stall items:    REAL — coordination nodes with type='coordination' and
            Open/Refining status carry `updated_at`; age is computable. Stall
            signals are live and accurate.
        """
        dated_items: list[dict] = []
        error_items: list[dict] = []
        stall_items: list[dict] = []

        # ── Deadline items — regex bridge (Task 5) ────────────────────────────
        # Scan Open/Refining coordination nodes for date-like strings in their
        # content text.  build_dated_items supports both regex-extracted dates
        # (fuzzy=True) and structured provenance["deadline_date"] (fuzzy=False,
        # takes precedence over regex for that node).
        # The write path for deadline_date is a separate follow-up; for now we
        # just read it if present.
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                con.row_factory = sqlite3.Row
                coord_rows = con.execute(
                    "SELECT id, content, updated_at, provenance FROM nodes "
                    "WHERE type = 'coordination'"
                ).fetchall()
            # Filter to Open/Refining only (same set the stall lane scans)
            active_rows = []
            for r in coord_rows:
                try:
                    prov = json.loads(r["provenance"] or "{}")
                except Exception:
                    prov = {}
                if prov.get("status") in ("Open", "Refining"):
                    active_rows.append(r)
            dated_items = build_dated_items(active_rows, now.date())
        except Exception:
            logger.exception(
                "heartbeat: _gather_material_signals deadline scan failed; "
                "returning [] for deadline lane"
            )
            dated_items = []

        # ── Error items ───────────────────────────────────────────────────────
        # GAP: no clean system-failure signal source in current schema.
        # Candidate: vett_patrol_state.last_error (currently empty).
        # fact-node content contains error-adjacent text but it's inbox relay
        # text, not machine-actionable system errors.

        # ── Stall items ───────────────────────────────────────────────────────
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT id, content, updated_at, provenance FROM nodes "
                    "WHERE type = 'coordination'"
                ).fetchall()
            for r in rows:
                prov = json.loads(r["provenance"] or "{}")
                status = prov.get("status")
                if status not in ("Open", "Refining"):
                    continue
                try:
                    age_hours = (
                        now - datetime.fromisoformat(r["updated_at"])
                    ).total_seconds() / 3600
                except (ValueError, TypeError):
                    continue
                first_line = (r["content"] or "").split("\n", 1)[0]
                ref = first_line[:80] or r["id"]
                stall_items.append({
                    "ref": ref,
                    "status": status,
                    "age_hours": age_hours,
                })
        except Exception:
            logger.exception(
                "heartbeat: _gather_material_signals stall query failed; "
                "returning [] for stall lane"
            )

        # ── Deploy clock → hours_since_deploy for stall amnesty (T6) ─────────
        # Best-effort: if the sentinel read/write fails, fall back to None
        # (legacy stall behavior — all >48h stalls flagged, no amnesty).
        hours_since_deploy: float | None = None
        try:
            deploy_started_at = get_deploy_started_at(self.deploy_sentinel, now)
            hours_since_deploy = (now - deploy_started_at).total_seconds() / 3600
        except Exception:
            logger.exception(
                "heartbeat: deploy-clock sentinel read/write failed; "
                "falling back to legacy stall behavior (hours_since_deploy=None)"
            )

        try:
            return detect_materiality(
                dated_items=dated_items,
                error_items=error_items,
                stall_items=stall_items,
                now=now,
                hours_since_deploy=hours_since_deploy,
            )
        except Exception:
            logger.exception(
                "heartbeat: detect_materiality raised unexpectedly; "
                "returning [] for material_signals"
            )
            return []

    # ─── Session + vnext invocation ─────────────────────────────────────────

    def _ensure_heartbeat_session(self) -> str:
        if self._heartbeat_session_id is not None:
            return self._heartbeat_session_id
        # Look for existing session by title.
        with sqlite3.connect(str(self.conv_db)) as con:
            row = con.execute(
                "SELECT session_id FROM conversation_meta "
                "WHERE agent = 'aetheria' AND title = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (HEARTBEAT_SESSION_TITLE,),
            ).fetchone()
        if row is not None:
            self._heartbeat_session_id = row[0]
            return self._heartbeat_session_id
        # No existing — create one via the API.
        payload = {"agent": "aetheria", "title": HEARTBEAT_SESSION_TITLE}
        resp = self._post_json("/sessions", payload, timeout=10)
        self._heartbeat_session_id = resp["session_id"]
        return self._heartbeat_session_id

    def _call_vnext_chat(self, session_id: str, message: str) -> dict:
        payload = {
            "agent": "aetheria", "session_id": session_id, "message": message,
            "source": "heartbeat",
        }
        return self._post_json("/chat", payload, timeout=CHAT_TIMEOUT_SECONDS)

    def _post_json(self, path: str, body: dict, *, timeout: int) -> dict:
        url = f"{self.vnext_base}{path}"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # vNext puts the real cause in the JSON body: /chat catches
            # AgentLoopError and returns {"error":{"code","message"}} with a 500
            # WITHOUT logging a traceback. urllib discards that body unless it is
            # read here, so the pulse log recorded a bare "HTTP Error 500:
            # INTERNAL SERVER ERROR" for five hours on 2026-08-01 while the
            # actual message sat unread in the response.
            detail = ""
            try:
                raw = e.read().decode("utf-8", "replace")[:600]
                try:
                    parsed = json.loads(raw).get("error") or {}
                    detail = f"{parsed.get('code','?')}: {parsed.get('message','')}"
                except ValueError:
                    detail = raw
            except Exception:  # pragma: no cover - body already consumed
                pass
            logger.error("heartbeat POST %s -> HTTP %s | %s", path, e.code, detail)
            raise HeartbeatHTTPError(
                f"HTTP {e.code} from {path}: {detail or e.reason}"
            ) from e

    def _summarise_response(self, response: dict) -> tuple[bool, int]:
        """Return (action_taken, tool_call_count). action_taken = the agent
        called at least one tool."""
        tool_calls = response.get("tool_calls") or []
        count = len(tool_calls) if isinstance(tool_calls, list) else 0
        return (count > 0, count)

    # ─── Audit log writes ───────────────────────────────────────────────────

    def _write_log_row(
        self,
        *,
        tick_id: str,
        triggered_at: str,
        completed_at: str | None,
        eligible: bool,
        skip_reason: str | None,
        action_taken: bool | None,
        tool_call_count: int | None,
        response_length: int | None,
        error: str | None,
    ) -> None:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                con.execute(
                    "INSERT INTO heartbeat_log "
                    "(id, triggered_at, completed_at, eligible, skip_reason, "
                    "action_taken, tool_call_count, response_length, error, "
                    "dry_run, surfaced_to_chat) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (tick_id, triggered_at, completed_at,
                     1 if eligible else 0,
                     skip_reason,
                     None if action_taken is None else (1 if action_taken else 0),
                     tool_call_count, response_length, error,
                     1 if self.config.dry_run else 0,
                     # Surfacing removed: pulse notes stay in the [heartbeat]
                     # session, never a "primary" chat — so always 0.
                     0),
                )
        except Exception:
            logger.exception("failed to write heartbeat_log row %s", tick_id)


def _gather_salience(salience_db: Path, *, since: datetime) -> str:
    """Decay-then-read-then-render. Returns '' on empty or error.

    Best-effort by contract — the heartbeat tick survives salience
    problems. Local imports keep the daemon's import-time surface lean
    (and let the test suite monkey-patch if needed).
    """
    from soveryn.platform.salience.store import (
        decay_old_pending, pending_candidates_since,
    )
    from soveryn.platform.salience.digest import build_salience_digest_section
    try:
        decay_old_pending(salience_db, older_than_days=14)
        cands = pending_candidates_since(salience_db, since=since, limit=20)
        return build_salience_digest_section(cands)
    except Exception:
        logger.exception("heartbeat: salience gather failed; using empty section")
        return ""


def _build_daemon_from_env() -> HeartbeatDaemon:
    """Construct a HeartbeatDaemon honoring env overrides.

    Extracted from _main so the env-wiring is testable without launching
    the run loop (which installs signal handlers + sleeps).
    """
    config = HeartbeatConfig.from_env()
    return HeartbeatDaemon(
        config,
        vnext_base=os.environ.get("SOVERYN_HEARTBEAT_VNEXT_BASE", DEFAULT_VNEXT_BASE),
        salience_db=Path(os.environ.get("SOVERYN_SALIENCE_DB", str(DEFAULT_SALIENCE_DB))),
        daily_post_hour=int(
            os.environ.get("SOVERYN_HEARTBEAT_DAILY_POST_HOUR", str(DEFAULT_DAILY_POST_HOUR))
        ),
        # Same file the Flask app opens. Must match startup.py's
        # env.data_root / "active_context.db" or the pulse writes into a store
        # nobody reads — the failure mode this whole layer exists to end.
        active_context_db=Path(
            os.environ.get(
                "SOVERYN_ACTIVE_CONTEXT_DB",
                str(DEFAULT_CONV_DB.parent.parent / "active_context.db"),
            )
        ),
        # Charter §12.5. Set SOVERYN_CITIZENS_DB="" to switch the bookkeeping
        # off entirely — the pulse is identical either way, and that is the
        # point: this records her duty, it does not govern it.
        citizens_db=(
            Path(_citizens_db_env)
            if (_citizens_db_env := os.environ.get(
                "SOVERYN_CITIZENS_DB",
                str(DEFAULT_CONV_DB.parent.parent / "citizens.db"),
            ))
            else None
        ),
    )


def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    daemon = _build_daemon_from_env()
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
