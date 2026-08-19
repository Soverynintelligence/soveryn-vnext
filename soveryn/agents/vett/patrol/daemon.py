"""V.E.T.T. patrol daemon process loop.

Separate process from vnext (Ares-style isolation). Talks to vnext over
the standard /chat endpoint with the Patrol Briefing prompt. Reads
source state + lattice activity directly from the lattice DB. Records
every tick to vett_patrol_log.

Run as a module: `python -m soveryn.agents.vett.patrol`.

Spin-bug resistance: last_patrol_at advances only on eligible ticks;
last_tick_at advances on every tick. Sleep math uses last_tick_at so
consecutive skipped ticks don't leave sleep_target stuck in the past
(the bug surfaced in heartbeat's 2026-06-02 dry-run bake).
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

from soveryn.agents.vett.patrol.prompt import (
    LatticeTagSnapshot,
    PatrolBriefingInputs,
    build_patrol_brief,
)
from soveryn.agents.vett.patrol.source_list import (
    PATROL_SOURCES_DEFAULT_PATH,
    PatrolSourceError,
    load_source_list,
    read_patrol_state,
)
from soveryn.agents.vett.patrol.trigger import (
    PatrolConfig,
    PatrolSkipReason,
    TickEligibility,
    evaluate_tick,
)


logger = logging.getLogger(__name__)


DEFAULT_LATTICE_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
DEFAULT_CONV_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"

# Window of recent lattice activity to summarise in the briefing.
LATTICE_WINDOW_MINUTES = 240   # 4h — slower cadence than heartbeat's hour

# Vett's durable patrol session title. Matches heartbeat's convention.
PATROL_SESSION_TITLE = "[patrol] vett"


class PatrolDaemon:
    """Single-threaded tick loop. One tick at a time."""

    def __init__(
        self,
        config: PatrolConfig,
        *,
        lattice_db: Path = DEFAULT_LATTICE_DB,
        conv_db: Path = DEFAULT_CONV_DB,
        sources_yaml_path: Path = PATROL_SOURCES_DEFAULT_PATH,
    ) -> None:
        self.config = config
        self.lattice_db = Path(lattice_db)
        self.conv_db = Path(conv_db)
        self.sources_yaml_path = Path(sources_yaml_path)
        self._stop = False
        self._patrol_session_id: str | None = None

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        logger.info(
            "patrol daemon starting. config=%s sources=%s",
            self.config, self.sources_yaml_path,
        )
        # Same spin-bug-resistant pattern as heartbeat.daemon.
        last_patrol_at = self._latest_patrol_completed_at()
        last_tick_at: datetime | None = None
        while not self._stop:
            now = datetime.now()
            last_activity_at = self._latest_vett_activity_at()
            source_count = self._safe_source_count()
            eligibility = evaluate_tick(
                self.config,
                now=now,
                last_patrol_at=last_patrol_at,
                last_vett_activity_at=last_activity_at,
                source_count=source_count,
            )
            self._do_tick(now=now, eligibility=eligibility)
            if eligibility.eligible:
                last_patrol_at = now
            last_tick_at = now  # always advance — the bug fix
            sleep_target = last_tick_at + timedelta(
                seconds=self.config.interval_seconds
            )
            while not self._stop and datetime.now() < sleep_target:
                time.sleep(min(5.0, max(0.1, (sleep_target - datetime.now()).total_seconds())))
        logger.info("patrol daemon stopped cleanly")

    def _handle_signal(self, *_: Any) -> None:
        logger.info("patrol daemon received shutdown signal")
        self._stop = True

    # ─── Per-tick work ──────────────────────────────────────────────────────

    def _do_tick(self, *, now: datetime, eligibility: TickEligibility) -> None:
        tick_id = str(uuid.uuid4())
        triggered_at = now.isoformat()
        if not eligibility.eligible:
            self._write_log_row(
                tick_id=tick_id,
                triggered_at=triggered_at,
                completed_at=now.isoformat(),
                eligible=False,
                skip_reason=eligibility.skip_reason.value if eligibility.skip_reason else None,
                sources_visited=None,
                signals_posted=None,
                response_length=None,
                error=None,
            )
            return

        # Eligible — build the briefing and invoke (unless dry-run).
        try:
            source_list = load_source_list(self.sources_yaml_path)
            urls = [s.url for s in source_list.sources]
            state_map = read_patrol_state(self.lattice_db, urls=urls)
            pairs = tuple((s, state_map[s.url]) for s in source_list.sources)
            lattice = self._gather_lattice_snapshot(now)
            last_patrol = self._latest_patrol_completed_at()
            hours_since: float | None = None
            if last_patrol is not None:
                hours_since = round(
                    (now - last_patrol).total_seconds() / 3600, 1
                )
            inputs = PatrolBriefingInputs(
                hours_since_last_patrol=hours_since,
                sources=pairs,
                lattice=lattice,
            )
            prompt = build_patrol_brief(inputs, now=now)
        except (PatrolSourceError, Exception) as e:
            logger.exception("patrol tick failed during context gathering")
            self._write_log_row(
                tick_id=tick_id,
                triggered_at=triggered_at,
                completed_at=datetime.now().isoformat(),
                eligible=True,
                skip_reason=None,
                sources_visited=None,
                signals_posted=None,
                response_length=None,
                error=f"{type(e).__name__}: {e}",
            )
            return

        if self.config.dry_run:
            logger.info(
                "patrol tick %s DRY-RUN. prompt (head): %r",
                tick_id, prompt[:300],
            )
            self._write_log_row(
                tick_id=tick_id,
                triggered_at=triggered_at,
                completed_at=datetime.now().isoformat(),
                eligible=True,
                skip_reason=None,
                sources_visited=0,   # dry-run never fetches
                signals_posted=0,
                response_length=len(prompt),
                error=None,
            )
            return

        # Live: invoke Vett via /chat with the durable patrol session.
        try:
            # Continuum — Vett is crew; same unprompted budget/ledger as Aetheria.
            from soveryn.platform.acttruth.unprompted import (
                apply_budget_to_prompt,
                record_unprompted_tick,
            )

            prompt, _budget = apply_budget_to_prompt(
                "vett", prompt, rail="patrol",
            )

            session_id = self._ensure_patrol_session()
            sources_before = self._patrol_visit_count_total()
            signals_before = self._signal_count_for_vett()
            response = self._call_vnext_chat(session_id, prompt)
            sources_after = self._patrol_visit_count_total()
            signals_after = self._signal_count_for_vett()
            sources_visited = max(0, sources_after - sources_before)
            signals_posted = max(0, signals_after - signals_before)
            response_text = response.get("content", "") if isinstance(response, dict) else ""
            tool_calls = response.get("tool_calls") or []
            tool_count = len(tool_calls) if isinstance(tool_calls, list) else 0
            action_taken = (
                sources_visited > 0
                or signals_posted > 0
                or tool_count > 0
            )
            record_unprompted_tick(
                "vett",
                rail="patrol",
                tick_id=tick_id,
                action_taken=action_taken,
                tool_call_count=tool_count,
                note_head=(response_text or "")[:120],
                extra_summary=(
                    f"sources_visited={sources_visited} "
                    f"signals_posted={signals_posted}"
                ),
            )
            if action_taken:
                try:
                    from soveryn.platform.acttruth.earned_keep import record_earned_keep

                    record_earned_keep(
                        "vett",
                        rail="patrol",
                        tick_id=tick_id,
                        durable_delta=(sources_visited > 0 or signals_posted > 0),
                    )
                except Exception:
                    logger.exception(
                        "patrol tick %s: earned_keep record failed", tick_id,
                    )
            self._write_log_row(
                tick_id=tick_id,
                triggered_at=triggered_at,
                completed_at=datetime.now().isoformat(),
                eligible=True,
                skip_reason=None,
                sources_visited=sources_visited,
                signals_posted=signals_posted,
                response_length=len(response_text),
                error=None,
            )
            logger.info(
                "patrol tick %s done. sources_visited=%d signals_posted=%d response_len=%d",
                tick_id, sources_visited, signals_posted, len(response_text),
            )
        except Exception as e:
            logger.exception("patrol tick failed during chat invocation")
            self._write_log_row(
                tick_id=tick_id,
                triggered_at=triggered_at,
                completed_at=datetime.now().isoformat(),
                eligible=True,
                skip_reason=None,
                sources_visited=None,
                signals_posted=None,
                response_length=None,
                error=f"{type(e).__name__}: {e}",
            )

    # ─── State queries (DB-direct) ──────────────────────────────────────────

    def _latest_patrol_completed_at(self) -> datetime | None:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                row = con.execute(
                    "SELECT completed_at FROM vett_patrol_log "
                    "WHERE completed_at IS NOT NULL "
                    "ORDER BY triggered_at DESC LIMIT 1"
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None or row[0] is None:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except ValueError:
            return None

    def _latest_vett_activity_at(self) -> datetime | None:
        """Most recent Vett session updated_at (user chat OR webhook), excluding
        the patrol session itself — we don't backoff against our own previous
        tick (that's the interval gate's job)."""
        try:
            with sqlite3.connect(str(self.conv_db)) as con:
                row = con.execute(
                    "SELECT MAX(updated_at) FROM conversation_meta "
                    "WHERE agent = 'vett' "
                    "AND (title IS NULL OR title != ?)",
                    (PATROL_SESSION_TITLE,),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None or row[0] is None:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except ValueError:
            return None

    def _safe_source_count(self) -> int:
        try:
            return len(load_source_list(self.sources_yaml_path))
        except PatrolSourceError as e:
            logger.warning("source list invalid; reporting 0 sources: %s", e)
            return 0

    def _gather_lattice_snapshot(self, now: datetime) -> LatticeTagSnapshot:
        window_start = (now - timedelta(minutes=LATTICE_WINDOW_MINUTES)).isoformat()
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                new_nodes = con.execute(
                    "SELECT COUNT(*) FROM nodes WHERE created_at >= ? "
                    "AND type NOT IN ('coordination', 'lesson_learned')",
                    (window_start,),
                ).fetchone()[0]
                tag_rows = con.execute(
                    "SELECT tags FROM nodes WHERE created_at >= ? "
                    "AND agent = 'aetheria' AND tags IS NOT NULL",
                    (window_start,),
                ).fetchall()
        except sqlite3.OperationalError:
            return LatticeTagSnapshot(
                tagged_domains=(),
                new_node_count_recent_window=0,
                recent_window_minutes=LATTICE_WINDOW_MINUTES,
            )
        # Tags column is JSON-encoded list[str]. Aggregate + dedupe.
        domains: set[str] = set()
        for r in tag_rows:
            try:
                tags = json.loads(r[0] or "[]")
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(tags, list):
                for t in tags:
                    if isinstance(t, str) and t.strip():
                        domains.add(t.strip())
        return LatticeTagSnapshot(
            tagged_domains=tuple(sorted(domains)),
            new_node_count_recent_window=int(new_nodes),
            recent_window_minutes=LATTICE_WINDOW_MINUTES,
        )

    def _patrol_visit_count_total(self) -> int:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                row = con.execute(
                    "SELECT COALESCE(SUM(visit_count), 0) FROM vett_patrol_state"
                ).fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row[0] or 0)

    def _signal_count_for_vett(self) -> int:
        """Count Vett-authored open Signals (proxy for 'signals_posted this tick')."""
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                rows = con.execute(
                    "SELECT provenance FROM nodes "
                    "WHERE agent = 'vett' AND type = 'coordination'"
                ).fetchall()
        except sqlite3.OperationalError:
            return 0
        count = 0
        for r in rows:
            try:
                prov = json.loads(r[0] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if prov.get("board") == "Signal" and prov.get("status") != "Archived":
                count += 1
        return count

    # ─── Session + vnext invocation ─────────────────────────────────────────

    def _ensure_patrol_session(self) -> str:
        if self._patrol_session_id is not None:
            return self._patrol_session_id
        with sqlite3.connect(str(self.conv_db)) as con:
            row = con.execute(
                "SELECT session_id FROM conversation_meta "
                "WHERE agent = 'vett' AND title = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (PATROL_SESSION_TITLE,),
            ).fetchone()
        if row is not None:
            self._patrol_session_id = row[0]
            return self._patrol_session_id
        payload = {"agent": "vett", "title": PATROL_SESSION_TITLE}
        resp = self._post_json("/sessions", payload, timeout=10)
        self._patrol_session_id = resp["session_id"]
        return self._patrol_session_id

    def _call_vnext_chat(self, session_id: str, message: str) -> dict:
        payload = {"agent": "vett", "session_id": session_id, "message": message}
        return self._post_json("/chat", payload, timeout=self.config.chat_timeout_seconds)

    def _post_json(self, path: str, body: dict, *, timeout: int) -> dict:
        url = f"{self.config.vnext_base.rstrip('/')}{path}"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    # ─── Audit log writes ───────────────────────────────────────────────────

    def _write_log_row(
        self,
        *,
        tick_id: str,
        triggered_at: str,
        completed_at: str | None,
        eligible: bool,
        skip_reason: str | None,
        sources_visited: int | None,
        signals_posted: int | None,
        response_length: int | None,
        error: str | None,
    ) -> None:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                con.execute(
                    "INSERT INTO vett_patrol_log "
                    "(id, triggered_at, completed_at, eligible, skip_reason, "
                    "sources_visited, signals_posted, response_length, error, dry_run) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (tick_id, triggered_at, completed_at,
                     1 if eligible else 0,
                     skip_reason,
                     sources_visited, signals_posted, response_length, error,
                     1 if self.config.dry_run else 0),
                )
        except Exception:
            logger.exception("failed to write vett_patrol_log row %s", tick_id)


def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = PatrolConfig.from_env()
    daemon = PatrolDaemon(config)
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
