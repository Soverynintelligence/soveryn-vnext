"""Automations scheduler daemon — tick due crons via vNext live run API.

Mirrors heartbeat: out-of-process loop, HTTP into soveryn-vnext so AgentLoops
and the Approval Gate stay in the Flask process.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

from soveryn.automations.schedule import due_automations

logger = logging.getLogger("soveryn.automations.daemon")

DEFAULT_VNEXT_BASE = "http://127.0.0.1:5001"
DEFAULT_TICK_SECONDS = 60


class AutomationsDaemon:
    def __init__(
        self,
        *,
        enabled: bool = True,
        tick_seconds: int = DEFAULT_TICK_SECONDS,
        vnext_base: str = DEFAULT_VNEXT_BASE,
    ) -> None:
        self.enabled = enabled
        self.tick_seconds = max(15, int(tick_seconds))
        self.vnext_base = vnext_base.rstrip("/")
        self._stop = False

    def _handle_signal(self, signum, frame) -> None:  # noqa: ARG002
        logger.info("automations daemon received signal %s", signum)
        self._stop = True

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        logger.info(
            "automations daemon starting enabled=%s tick=%ss vnext=%s",
            self.enabled,
            self.tick_seconds,
            self.vnext_base,
        )
        while not self._stop:
            if self.enabled:
                try:
                    self._tick()
                except Exception:
                    logger.exception("automations tick failed")
            else:
                logger.debug("automations disabled; sleeping")
            # Interruptible sleep
            deadline = time.time() + self.tick_seconds
            while not self._stop and time.time() < deadline:
                time.sleep(min(1.0, deadline - time.time()))
        logger.info("automations daemon stopped cleanly")

    def _tick(self) -> None:
        now = datetime.now()
        due = due_automations(now=now)
        if not due:
            logger.debug("automations tick %s: nothing due", now.isoformat(timespec="seconds"))
            return
        logger.info(
            "automations tick %s: %d due (%s)",
            now.isoformat(timespec="seconds"),
            len(due),
            ", ".join(s.id for s in due),
        )
        for spec in due:
            if self._stop:
                break
            self._fire(spec.id)

    def _fire(self, automation_id: str) -> None:
        url = f"{self.vnext_base}/api/automations/{automation_id}/run"
        payload = json.dumps({"live": True, "source": "scheduler"}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace"))
            ok = bool(body.get("ok"))
            logger.info(
                "automations fire %s → %s inbox=%s",
                automation_id,
                "ok" if ok else "fail",
                bool(body.get("inbox")),
            )
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "replace")[:400]
            logger.error(
                "automations fire %s HTTP %s: %s",
                automation_id,
                e.code,
                err_body,
            )
        except Exception:
            logger.exception("automations fire %s failed", automation_id)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    enabled = os.environ.get("SOVERYN_AUTOMATIONS_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )
    tick = int(os.environ.get("SOVERYN_AUTOMATIONS_TICK_SECONDS", str(DEFAULT_TICK_SECONDS)))
    base = os.environ.get("SOVERYN_AUTOMATIONS_VNEXT_BASE", DEFAULT_VNEXT_BASE)
    # Documented gate — daemon never arms Signal itself.
    if os.environ.get("SOVERYN_AUTOMATIONS_SIGNAL_LIVE", "false").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        logger.warning(
            "SOVERYN_AUTOMATIONS_SIGNAL_LIVE is set but Signal send is not "
            "implemented in this pass — CC inbox only"
        )
    AutomationsDaemon(enabled=enabled, tick_seconds=tick, vnext_base=base).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
