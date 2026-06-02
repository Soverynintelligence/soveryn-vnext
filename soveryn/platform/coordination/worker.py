"""Background worker that pulls CoordEvents from an InMemoryEventBus,
routes them, and dispatches to destination agents.

One worker thread total. Errors during dispatch are logged but never
propagate to the queue — one failure doesn't poison the rest. Chain depth
cap prevents runaway event chains (e.g., agent A triggers B who triggers
A again with the same kind).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from queue import Empty

from soveryn.platform.coordination.events import (
    MAX_CHAIN_DEPTH,
    CoordEvent,
    InMemoryEventBus,
)
from soveryn.platform.coordination.dispatcher import AgentDispatcher
from soveryn.platform.coordination.routing import route


logger = logging.getLogger(__name__)


class CoordEventWorker:
    """Single background thread pulling from one InMemoryEventBus."""

    def __init__(
        self,
        bus: InMemoryEventBus,
        dispatcher: AgentDispatcher,
        *,
        lattice_db_path: Path,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self.bus = bus
        self.dispatcher = dispatcher
        self.lattice_db_path = Path(lattice_db_path)
        self.poll_interval_seconds = poll_interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="coord-event-worker", daemon=True,
        )
        self._thread.start()
        logger.info("coord event worker started")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("coord event worker stopped")

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self.bus.get(timeout=self.poll_interval_seconds)
            except Empty:
                continue
            try:
                self._handle_event(event)
            except Exception:
                logger.exception("coord worker crashed on event %s", event.id)
            finally:
                self.bus.task_done()

    def _handle_event(self, event: CoordEvent) -> None:
        # Loop prevention: drop events that exceed the chain-depth cap.
        if event.chain_depth >= MAX_CHAIN_DEPTH:
            logger.warning(
                "dropping event %s (kind=%s, depth=%d) — chain_depth cap reached",
                event.id, event.kind.value, event.chain_depth,
            )
            self._mark_triggered(event.id, "DROPPED: chain_depth cap")
            return

        destinations = route(event)
        if not destinations:
            self._mark_triggered(event.id, "")  # empty = no destinations
            return

        succeeded: list[str] = []
        errors: list[str] = []
        for dest in destinations:
            try:
                self.dispatcher.dispatch(event, dest)
                succeeded.append(dest)
            except Exception as e:
                logger.exception(
                    "dispatch failed for event %s to %s", event.id, dest,
                )
                errors.append(f"{dest}=ERROR:{type(e).__name__}")
        triggered_summary = ",".join(succeeded + errors)
        self._mark_triggered(event.id, triggered_summary)

    def _mark_triggered(self, event_id: str, triggered_agents: str) -> None:
        """Update the coord_event_log row with the dispatch outcome. Best-effort —
        failure here doesn't block anything."""
        try:
            con = sqlite3.connect(str(self.lattice_db_path), timeout=30.0)
            try:
                con.execute(
                    "UPDATE coord_event_log SET triggered_agents = ? WHERE id = ?",
                    (triggered_agents, event_id),
                )
                con.commit()
            finally:
                con.close()
        except Exception:
            logger.warning(
                "failed to record triggered_agents for event %s", event_id,
                exc_info=True,
            )
