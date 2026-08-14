"""Scotty's process residence — always-on worker for the house repair desk.

Charter §6: residence needs a live process, not only "invoked when needed."
This daemon is that process. It:

  1. Touches Scotty's desk so presence is visible on disk.
  2. Asks vNext to drain Scotty's commission queue (localhost).
  3. Sleeps and repeats.

Inference still runs on Spark Qwen via AgentLoop inside vNext — this unit is
the *process* half of residence, like Vett's patrol unit.

Usage:
  python -m soveryn.citizens.scotty_worker
  SOVERYN_SCOTTY_WORKER_POLL=15
  SOVERYN_VNEXT_BASE=http://127.0.0.1:5001
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("soveryn.citizens.scotty_worker")

DESK = Path.home() / "soveryn_citizens" / "scotty"
DEFAULT_BASE = "http://127.0.0.1:5001"
POLL = float(os.environ.get("SOVERYN_SCOTTY_WORKER_POLL", "15"))


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def touch_desk() -> None:
    DESK.mkdir(parents=True, exist_ok=True)
    for sub in ("inbox", "outbox", "work", "notes"):
        (DESK / sub).mkdir(parents=True, exist_ok=True)
    stamp = DESK / "notes" / "worker_alive"
    stamp.write_text(
        f"scotty worker alive at {_utc()}\n"
        f"poll={POLL}s\n"
        f"desk={DESK}\n",
        encoding="utf-8",
    )


def drain_once(base: str) -> dict:
    """Ask vNext to drain Scotty's queue once. Returns JSON body or error dict."""
    url = base.rstrip("/") + "/api/citizens/runtime/drain"
    payload = json.dumps({"citizen_id": "scotty"}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "scotty-worker/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {exc.code}", "body": body[:500]}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}


def run_forever() -> None:
    base = os.environ.get("SOVERYN_VNEXT_BASE", DEFAULT_BASE)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("scotty worker starting base=%s poll=%ss desk=%s", base, POLL, DESK)
    while True:
        try:
            touch_desk()
            result = drain_once(base)
            closed = result.get("closed") or []
            if closed:
                for row in closed:
                    logger.info(
                        "drained %s → %s",
                        row.get("id", "?")[:8],
                        row.get("state"),
                    )
            elif not result.get("ok", True) and result.get("error"):
                logger.warning("drain: %s", result.get("error"))
            else:
                logger.debug("idle — no scotty commissions")
        except Exception:
            logger.exception("scotty worker loop error")
        time.sleep(POLL)


def main(argv: list[str] | None = None) -> int:
    run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
