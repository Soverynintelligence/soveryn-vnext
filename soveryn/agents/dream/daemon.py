"""Dream daemon process loop.

Mirrors heartbeat/patrol shape. Spin-bug-resistant pattern (last_dream_at
vs last_tick_at, same as 0fb715b). SIGTERM/SIGINT triggers graceful
shutdown.

Run as: `python -m soveryn.agents.dream`.
"""

from __future__ import annotations

import json
import logging
import signal
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from soveryn.agents.dream.cognition import (
    CognitionResult,
    run_three_pass,
)
from soveryn.agents.dream.config import DreamConfig
from soveryn.agents.dream.prompt import DreamBriefing, NodeSummary
from soveryn.agents.dream.trigger import (
    DreamSkipReason,
    TickEligibility,
    evaluate_tick,
)
from soveryn.agents.dream.writeback import write_dream_outputs


logger = logging.getLogger(__name__)


DEFAULT_LATTICE_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
DEFAULT_CONV_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"
DEFAULT_TICK_INTERVAL_SECONDS = 600  # 10 minutes — checks gates every 10 min during window


class DreamDaemon:
    """Single-threaded tick loop with spin-bug-resistant sleep math."""

    def __init__(
        self,
        config: DreamConfig,
        *,
        lattice_db: Path = DEFAULT_LATTICE_DB,
        conv_db: Path = DEFAULT_CONV_DB,
        tick_interval_seconds: int = DEFAULT_TICK_INTERVAL_SECONDS,
    ) -> None:
        self.config = config
        self.lattice_db = Path(lattice_db)
        self.conv_db = Path(conv_db)
        self.tick_interval_seconds = tick_interval_seconds
        self._stop = False

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        logger.info(
            "dream daemon starting. config=%s tick_interval=%ds",
            self.config, self.tick_interval_seconds,
        )
        # Spin-bug-resistant sleep math (matches heartbeat 0fb715b):
        # last_dream_at advances only on eligible ticks (that's the gate
        # logic's job). last_tick_at advances EVERY tick so sleep_target
        # never sticks in the past on consecutive skipped ticks.
        last_tick_at: datetime | None = None
        while not self._stop:
            now = datetime.now()
            try:
                self._do_tick(now=now)
            except Exception:
                logger.exception("tick failed")
            last_tick_at = now  # always advance — the spin-bug fix
            sleep_target = last_tick_at + timedelta(seconds=self.tick_interval_seconds)
            while not self._stop and datetime.now() < sleep_target:
                time.sleep(min(0.5, max(0.05, (sleep_target - datetime.now()).total_seconds())))
        logger.info("dream daemon stopped cleanly")

    def _handle_signal(self, *_: Any) -> None:
        logger.info("dream daemon received shutdown signal")
        self._stop = True

    # ─── Per-tick work ──────────────────────────────────────────────────────

    def _do_tick(self, *, now: datetime) -> None:
        last_dream_at = self._latest_dream_at()
        last_activity_at = self._latest_aetheria_activity_at()
        new_input_count = self._new_input_count_since(last_dream_at)
        eligibility = evaluate_tick(
            self.config, now=now,
            last_dream_at=last_dream_at,
            last_activity_at=last_activity_at,
            new_node_count_since_last_dream=new_input_count,
        )
        if not eligibility.eligible:
            logger.debug(
                "skipped tick: %s",
                eligibility.skip_reason.value if eligibility.skip_reason else "?",
            )
            return

        dream_run_id = str(uuid.uuid4())
        nodes = self._gather_nodes_for_briefing(last_dream_at)
        briefing = DreamBriefing(
            hours_since_last_dream=(
                round((now - last_dream_at).total_seconds() / 3600, 1)
                if last_dream_at else None
            ),
            nodes=nodes,
            board_summary=self._gather_board_summary(),
            recent_daemon_activity=self._gather_recent_daemon_activity(),
            recent_library_writes_count=self._count_recent_library_writes(last_dream_at),
        )

        if self.config.dry_run:
            logger.info(
                "dream tick %s DRY-RUN. nodes=%d",
                dream_run_id, len(nodes),
            )
            write_dream_outputs(
                self.lattice_db,
                dream_run_id=dream_run_id,
                synthesis="(dry-run)",
                associations="(dry-run)", contradictions="(dry-run)",
                loop_health=0.0,
                nodes_read=len(nodes),
                is_dry_run=True,
            )
            return

        # Live: run the three-pass cognition loop.
        try:
            result: CognitionResult = run_three_pass(
                briefing=briefing,
                cognition_url=self.config.cognition_url,
                timeout_seconds=self.config.cognition_timeout_seconds,
                max_internal_iterations=self.config.max_internal_iterations,
            )
        except Exception as e:
            logger.exception("cognition orchestrator crashed")
            write_dream_outputs(
                self.lattice_db,
                dream_run_id=dream_run_id,
                synthesis="",
                associations="", contradictions="",
                loop_health=0.0,
                nodes_read=len(nodes),
                is_dry_run=False,
            )
            return

        write_dream_outputs(
            self.lattice_db,
            dream_run_id=dream_run_id,
            synthesis=result.synthesis,
            associations=result.associations,
            contradictions=result.contradictions,
            loop_health=result.loop_health,
            nodes_read=len(nodes),
            is_dry_run=False,
        )
        logger.info(
            "dream tick %s done. iterations=%d loop_health=%.2f synthesis_len=%d",
            dream_run_id, result.iterations_completed,
            result.loop_health, len(result.synthesis or ""),
        )

    # ─── State queries (DB-direct) ──────────────────────────────────────────

    def _latest_dream_at(self) -> datetime | None:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                row = con.execute(
                    "SELECT ran_at FROM dream_log "
                    "WHERE ran_at IS NOT NULL "
                    "ORDER BY ran_at DESC LIMIT 1"
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None or row[0] is None:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except ValueError:
            return None

    def _latest_aetheria_activity_at(self) -> datetime | None:
        """Most recent Aetheria session updated_at (excluding [heartbeat],
        [signal], [patrol] daemon sessions — those are autonomous, not Jon)."""
        try:
            with sqlite3.connect(str(self.conv_db)) as con:
                row = con.execute(
                    "SELECT MAX(updated_at) FROM conversation_meta "
                    "WHERE agent = 'aetheria' "
                    "AND (title IS NULL OR ("
                    "  title NOT LIKE '[heartbeat]%' "
                    "  AND title NOT LIKE '[signal]%' "
                    "))"
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None or row[0] is None:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except ValueError:
            return None

    def _new_node_count_since(self, since: datetime | None) -> int:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                if since is None:
                    return con.execute(
                        "SELECT COUNT(*) FROM nodes"
                    ).fetchone()[0]
                return con.execute(
                    "SELECT COUNT(*) FROM nodes WHERE created_at > ?",
                    (since.isoformat(),),
                ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def _new_conv_turn_count_since(self, since: datetime | None) -> int:
        """Count of Aetheria's conversation turns since the given time,
        excluding daemon-driven sessions (heartbeat, signal, patrol) so
        autonomous polling doesn't inflate the count.

        Added 2026-06-08: the original NOTHING_TO_DREAM_ABOUT gate looked
        at lattice nodes only, but Aetheria's day mostly happens in
        conversations — they're real input the dream should synthesize."""
        try:
            with sqlite3.connect(str(self.conv_db)) as con:
                base_sql = (
                    "SELECT COUNT(*) FROM conversations c "
                    "WHERE c.agent = 'aetheria' "
                    "  AND c.session_id IN ("
                    "    SELECT session_id FROM conversation_meta "
                    "    WHERE agent = 'aetheria' AND ("
                    "      title IS NULL OR ("
                    "        title NOT LIKE '[heartbeat]%' "
                    "        AND title NOT LIKE '[signal]%' "
                    "        AND title NOT LIKE '[patrol]%' "
                    "        AND title NOT LIKE '[webhook]%'"
                    "      )"
                    "    )"
                    "  )"
                )
                if since is None:
                    return con.execute(base_sql).fetchone()[0]
                return con.execute(
                    base_sql + " AND c.timestamp > ?",
                    (since.isoformat(),),
                ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def _new_input_count_since(self, since: datetime | None) -> int:
        """Total inputs that count as 'something to dream about' since the
        last dream: new lattice nodes + new non-daemon conversation turns.

        Pre-2026-06-08 this was lattice-only, which caused the dream
        daemon to skip every night after 2026-06-05 even though Aetheria
        was having hundreds of conversation turns per day. The dream's
        purpose is to synthesize her experience, which mostly lives in
        the conv_store, not the lattice."""
        return (
            self._new_node_count_since(since)
            + self._new_conv_turn_count_since(since)
        )

    def _gather_nodes_for_briefing(self, since: datetime | None) -> tuple[NodeSummary, ...]:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                con.row_factory = sqlite3.Row
                if since is None:
                    rows = con.execute(
                        "SELECT id, agent, type, content FROM nodes "
                        "WHERE layer != ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        ("dream", self.config.nodes_per_run),
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT id, agent, type, content FROM nodes "
                        "WHERE created_at > ? AND layer != ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (since.isoformat(), "dream", self.config.nodes_per_run),
                    ).fetchall()
        except sqlite3.OperationalError:
            return ()
        return tuple(
            NodeSummary(
                id=r["id"],
                agent=r["agent"] or "",
                node_type=r["type"] or "",
                content_head=(r["content"] or "")[:200],
            )
            for r in rows
        )

    def _gather_board_summary(self) -> str:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                rows = con.execute(
                    "SELECT provenance FROM nodes WHERE type = 'coordination'"
                ).fetchall()
        except sqlite3.OperationalError:
            return "Signal: 0 / Blueprint: 0 / Friction: 0"
        signal_count = 0
        bp_count = 0
        friction_count = 0
        for r in rows:
            try:
                prov = json.loads(r[0] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if prov.get("status") == "Archived":
                continue
            board = prov.get("board")
            if board == "Signal":
                signal_count += 1
            elif board == "Blueprint":
                bp_count += 1
            elif board == "Friction":
                friction_count += 1
        return f"Signal: {signal_count} / Blueprint: {bp_count} open / Friction: {friction_count}"

    def _gather_recent_daemon_activity(self) -> str:
        """Last 24h of heartbeat + patrol audit summaries."""
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                hb = con.execute(
                    "SELECT COUNT(*) FROM heartbeat_log "
                    "WHERE eligible = 1 AND triggered_at > ?",
                    (cutoff,),
                ).fetchone()[0]
                pat = con.execute(
                    "SELECT COUNT(*), COALESCE(SUM(dry_run), 0) FROM vett_patrol_log "
                    "WHERE eligible = 1 AND triggered_at > ?",
                    (cutoff,),
                ).fetchone()
        except sqlite3.OperationalError:
            return "no recent daemon activity"
        return f"heartbeat {hb} eligible ticks; patrol {pat[0]} eligible ticks ({pat[1]} dry-run)"

    def _count_recent_library_writes(self, since: datetime | None) -> int:
        if since is None:
            since_iso = (datetime.now() - timedelta(hours=24)).isoformat()
        else:
            since_iso = since.isoformat()
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                return con.execute(
                    "SELECT COUNT(*) FROM nodes "
                    "WHERE layer = 'library' AND created_at > ?",
                    (since_iso,),
                ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0


def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = DreamConfig.from_env()
    daemon = DreamDaemon(config)
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
