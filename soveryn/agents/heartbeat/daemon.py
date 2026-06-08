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

from soveryn.agents.heartbeat.prompt import (
    BoardSnapshot,
    LatticeSnapshot,
    build_heartbeat_prompt,
)
from soveryn.agents.heartbeat.trigger import (
    HeartbeatConfig,
    SkipReason,
    TickEligibility,
    evaluate_tick,
)


logger = logging.getLogger(__name__)

# Defaults — overridable via env.
DEFAULT_VNEXT_BASE = "http://127.0.0.1:5001"
DEFAULT_LATTICE_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db")
DEFAULT_CONV_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/conversations_vnext.db")

# Window of lattice activity to summarise in the brief (separate from the
# interval/backoff knobs since this is a *content* knob not a *timing* knob).
LATTICE_WINDOW_MINUTES = 60

# A Blueprint is "stalled" if it's been in Refining longer than this without
# moving. Heuristic; tunable.
STALLED_BLUEPRINT_THRESHOLD_MINUTES = 240  # 4 hours

# How long the daemon waits for vnext to return Aetheria's response. Real
# generation can take 30-90s depending on prompt+thinking budget.
CHAT_TIMEOUT_SECONDS = 240

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
    ) -> None:
        self.config = config
        self.vnext_base = vnext_base.rstrip("/")
        self.lattice_db = Path(lattice_db)
        self.conv_db = Path(conv_db)
        self._stop = False
        self._heartbeat_session_id: str | None = None

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
            prompt = build_heartbeat_prompt(
                minutes_since_last_heartbeat=minutes_since,
                board=board,
                lattice=lattice,
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
        try:
            session_id = self._ensure_heartbeat_session()
            response = self._call_vnext_chat(session_id, prompt)
            action_taken, tool_call_count = self._summarise_response(response)
            response_text = response.get("content", "") if isinstance(response, dict) else ""
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
                "heartbeat tick %s done. action_taken=%s tool_calls=%s response_len=%d",
                tick_id, action_taken, tool_call_count, len(response_text),
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
        payload = {"agent": "aetheria", "session_id": session_id, "message": message}
        return self._post_json("/chat", payload, timeout=CHAT_TIMEOUT_SECONDS)

    def _post_json(self, path: str, body: dict, *, timeout: int) -> dict:
        url = f"{self.vnext_base}{path}"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

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
                    "action_taken, tool_call_count, response_length, error, dry_run) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (tick_id, triggered_at, completed_at,
                     1 if eligible else 0,
                     skip_reason,
                     None if action_taken is None else (1 if action_taken else 0),
                     tool_call_count, response_length, error,
                     1 if self.config.dry_run else 0),
                )
        except Exception:
            logger.exception("failed to write heartbeat_log row %s", tick_id)


def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = HeartbeatConfig.from_env()
    daemon = HeartbeatDaemon(
        config,
        vnext_base=os.environ.get("SOVERYN_HEARTBEAT_VNEXT_BASE", DEFAULT_VNEXT_BASE),
    )
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
