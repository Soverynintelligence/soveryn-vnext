"""Drain the commissions queue — one at a time per citizen (charter §12.4).

The runtime does not decide *what* work exists; that is Jon (or a duty) via
`enqueue`. It only claims the oldest queued row for each idle citizen, runs the
citizen's AgentLoop (or an injected process_fn in tests), writes the result to
the citizen's outbox, and closes the commission with a result_ref someone can
open.

Why one at a time
-----------------
Aetheria's GPU is a single slot (charter §8). Two concurrent commissions on her
would queue on the router, thrash cache, and make timeout diagnosis unreadable.
`claim` already prevents two workers from taking the *same* row; this module
also refuses to claim a second while one is still `running` for that citizen.

Interactive contention (product feel)
-------------------------------------
A background commission on Aetheria and a live chat turn will contend for the
same Blackwell slot. So drain also refuses to claim when an optional busy_fn
reports the citizen is mid-interactive work (recent direct user turns). Duty
bookkeeping pulses never sit in `queued` (see pulse.begin_owned), so they are
not drainable.

Outbox is the product surface
-----------------------------
Success without a file is forbidden by complete(). The path written here is
`~/soveryn_citizens/<id>/outbox/<commission_id>.md` (or the citizen's configured
workspace). That is what the Phase 2 exit criterion means by "result appears
without interactive UI".
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from soveryn.citizens import commissions
from soveryn.citizens.census import DESK_DIRS
from soveryn.citizens.registry import connect, list_citizens

logger = logging.getLogger(__name__)

ProcessFn = Callable[[str, str, str], str]
# (citizen_id, body, commission_id) -> result text
BusyFn = Callable[[str], bool]
# (citizen_id) -> True if a background claim should wait


# Sources that mean a human is talking — not heartbeat/commission bookkeeping.
_INTERACTIVE_SOURCES = frozenset({"direct", "messenger", "signal", "voice"})
# How recent a direct turn must be to count as "busy".
_DEFAULT_INTERACTIVE_BUSY_SECONDS = 90


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def interactive_busy(
    conv_db: str | Path | None,
    citizen_id: str,
    *,
    within_seconds: int = _DEFAULT_INTERACTIVE_BUSY_SECONDS,
    now: datetime | None = None,
) -> bool:
    """True if this citizen has a recent interactive user turn.

    Used so the drain worker does not start a commission while Jon is mid-
    conversation on the same GPU. Fail-open: any DB error returns False so a
    locked conv store cannot freeze the queue forever.
    """
    if conv_db is None:
        return False
    path = Path(conv_db)
    if not path.exists():
        return False
    when = now or datetime.now()
    # timestamps in the store are isoformat without guaranteed tz; compare as text
    # floor by subtracting seconds then isoformat for a coarse bound.
    floor = (when - timedelta(seconds=within_seconds)).isoformat()
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=2.0) as conn:
            placeholders = ",".join("?" for _ in _INTERACTIVE_SOURCES)
            row = conn.execute(
                f"""
                SELECT 1 FROM conversations
                 WHERE agent = ?
                   AND role = 'user'
                   AND source IN ({placeholders})
                   AND timestamp >= ?
                 LIMIT 1
                """,
                (citizen_id, *_INTERACTIVE_SOURCES, floor),
            ).fetchone()
            return row is not None
    except Exception:
        logger.debug(
            "interactive_busy check failed for %s; treating as idle",
            citizen_id,
            exc_info=True,
        )
        return False


def write_outbox(
    workspace_path: str | Path,
    commission_id: str,
    *,
    body: str,
    content: str,
    citizen_id: str,
) -> Path:
    """Write the commission result under outbox/ and return the absolute path."""
    root = Path(workspace_path)
    # ensure desk drawers exist even if census never ran for this path
    for name in DESK_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    path = root / "outbox" / f"{commission_id}.md"
    text = (
        f"# Commission result\n\n"
        f"- **citizen:** {citizen_id}\n"
        f"- **commission:** {commission_id}\n"
        f"- **written_at:** {_utc_now()}\n\n"
        f"## Task\n\n{body.strip()}\n\n"
        f"## Result\n\n{(content or '').strip() or '_(empty response)_'}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def execute_claimed(
    db_path: str | Path,
    claimed: dict,
    *,
    process_fn: ProcessFn,
    at: str | None = None,
) -> dict:
    """Run one already-claimed commission to done or failed. Returns final row."""
    when = at or _utc_now()
    commission_id = claimed["id"]
    citizen_id = claimed["citizen_id"]
    body = claimed["body"]

    workspace = _workspace_for(db_path, citizen_id)
    try:
        content = process_fn(citizen_id, body, commission_id)
        out_path = write_outbox(
            workspace, commission_id, body=body, content=content, citizen_id=citizen_id
        )
        with connect(db_path) as conn:
            commissions.complete(
                conn, commission_id, result_ref=str(out_path), at=when
            )
            row = commissions.get(conn, commission_id)
            # Report upward so COS (and the board) see outcomes without Jon
            # hunting outboxes. Self-posts from COS are skipped inside report_to_cos.
            try:
                from soveryn.citizens import post as house_post

                excerpt = (content or "").strip()
                if len(excerpt) > 1200:
                    excerpt = excerpt[:1200] + "…"
                house_post.report_to_cos(
                    conn,
                    from_id=citizen_id,
                    body=(
                        f"Commission `{commission_id}` **done**.\n\n"
                        f"**Task:** {body.strip()[:500]}\n\n"
                        f"**Result:**\n{excerpt}\n\n"
                        f"_outbox: {out_path}_"
                    ),
                    at=when,
                    commission_id=commission_id,
                    subject=f"done · {citizen_id}",
                )
            except Exception:
                logger.exception(
                    "house post report failed for commission %s", commission_id
                )
    except Exception as exc:
        logger.exception(
            "commission %s for %s failed", commission_id, citizen_id
        )
        with connect(db_path) as conn:
            try:
                commissions.fail(
                    conn, commission_id, error=repr(exc), at=when
                )
            except Exception:
                logger.exception(
                    "could not mark commission %s failed", commission_id
                )
            try:
                from soveryn.citizens import post as house_post

                house_post.report_to_cos(
                    conn,
                    from_id=citizen_id,
                    body=(
                        f"Commission `{commission_id}` **failed**.\n\n"
                        f"**Task:** {body.strip()[:500]}\n\n"
                        f"**Error:** {exc!r}"
                    ),
                    at=when,
                    commission_id=commission_id,
                    subject=f"failed · {citizen_id}",
                )
            except Exception:
                logger.exception(
                    "house post failure report failed for %s", commission_id
                )
            row = commissions.get(conn, commission_id)
    assert row is not None
    return row


def drain_once(
    db_path: str | Path,
    *,
    process_fn: ProcessFn,
    worker: str = "citizens-runtime",
    citizen_ids: list[str] | None = None,
    at: str | None = None,
    busy_fn: BusyFn | None = None,
) -> list[dict]:
    """Claim and execute at most one commission per idle citizen. Returns closed rows."""
    when = at or _utc_now()
    closed: list[dict] = []

    with connect(db_path) as conn:
        if citizen_ids is None:
            roster = list_citizens(conn)
            citizen_ids = [
                r["id"] for r in roster if not r.get("retired_at")
            ]
        # snapshot who is free and claim while still holding the connection so
        # the "already running" check and claim stay consistent.
        claimed_rows: list[dict] = []
        for cid in citizen_ids:
            if commissions.is_running(conn, cid):
                continue
            if busy_fn is not None:
                try:
                    busy = busy_fn(cid)
                except Exception:
                    # Fail open: a broken busy check must not freeze the queue.
                    logger.exception(
                        "busy_fn failed for %s; treating as idle", cid
                    )
                    busy = False
                if busy:
                    logger.info(
                        "citizens runtime: skip claim for %s — interactive busy",
                        cid,
                    )
                    continue
            claimed = commissions.claim(
                conn, cid, worker=worker, at=when
            )
            if claimed is not None:
                claimed_rows.append(claimed)

    for claimed in claimed_rows:
        closed.append(
            execute_claimed(db_path, claimed, process_fn=process_fn, at=when)
        )
    return closed


def run_forever(
    db_path: str | Path,
    *,
    process_fn: ProcessFn,
    worker: str = "citizens-runtime",
    poll_seconds: float = 5.0,
    citizen_ids: list[str] | None = None,
    busy_fn: BusyFn | None = None,
    _run_once_and_stop: bool = False,
) -> None:
    """Poll the commissions queue until stopped (daemon-thread friendly)."""
    logger.info(
        "citizens runtime starting db=%s poll=%ss", db_path, poll_seconds
    )
    while True:
        try:
            closed = drain_once(
                db_path,
                process_fn=process_fn,
                worker=worker,
                citizen_ids=citizen_ids,
                busy_fn=busy_fn,
            )
            if closed:
                for row in closed:
                    logger.info(
                        "commission %s %s → %s ref=%s",
                        row["id"],
                        row["citizen_id"],
                        row["state"],
                        row.get("result_ref") or row.get("error"),
                    )
        except Exception:
            logger.exception("citizens runtime drain failed; will retry")
        if _run_once_and_stop:
            return
        time.sleep(poll_seconds)


def make_agent_process_fn(agent_loops: dict, conv_store) -> ProcessFn:
    """Build a process_fn that drives each citizen's AgentLoop into a session."""

    def process(citizen_id: str, body: str, commission_id: str) -> str:
        loop = agent_loops.get(citizen_id)
        if loop is None:
            raise RuntimeError(
                f"no AgentLoop registered for citizen {citizen_id!r}"
            )
        session_id = conv_store.new_session(
            citizen_id, title=f"[commission] {commission_id[:8]}"
        )
        prompt = (
            f"[COMMISSION {commission_id}]\n"
            "You are executing a house commission — discrete work Jon (or a "
            "duty) placed on your desk. Complete the task. Write a clear, "
            "self-contained result a human can read without the chat UI.\n\n"
            f"{body.strip()}"
        )
        response = loop.process_message(
            session_id, prompt, source="commission"
        )
        return response.content or ""

    return process


def _workspace_for(db_path: str | Path, citizen_id: str) -> Path:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT workspace_path FROM citizens WHERE id = ?", (citizen_id,)
        ).fetchone()
    if row is None:
        raise KeyError(citizen_id)
    path = row["workspace_path"]
    if not path:
        path = str(Path.home() / "soveryn_citizens" / citizen_id)
    root = Path(path)
    for name in DESK_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root
