"""Fire-and-forget Messages turns for Kernel / Grok.

The phone composer must not own the HTTP thread until GLM or Grok CLI
finishes. Persist the user turn, enqueue a commission, ack, keep working
in a daemon thread. Result lands on the same session.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MARK = "[MESSAGES_TURN]"
ACK = "On it — working in the background. This thread stays yours."


def format_messages_turn(session_id: str, message: str) -> str:
    return f"{MARK}\nsession_id: {session_id}\n\n{message.strip()}\n"


def parse_messages_turn(body: str) -> tuple[str, str] | None:
    text = (body or "").lstrip()
    if not text.startswith(MARK):
        return None
    rest = text[len(MARK) :].lstrip("\n")
    if not rest.lower().startswith("session_id:"):
        return None
    first, _, remainder = rest.partition("\n")
    sid = first.split(":", 1)[-1].strip()
    if not sid:
        return None
    return sid, remainder.lstrip("\n")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def enqueue_messages_turn(
    *,
    agent: str,
    session_id: str,
    message: str,
    conv_store,
    db_path: Path,
) -> str:
    """Save the user turn, queue the commission. Returns commission id."""
    from soveryn.citizens import commissions
    from soveryn.citizens.registry import connect

    conv_store.save_turn(session_id, agent, "user", message, source="deferred")
    body = format_messages_turn(session_id, message)
    when = _utc_now()
    with connect(db_path) as conn:
        from soveryn.citizens.registry import Citizen, register

        if conn.execute(
            "SELECT 1 FROM citizens WHERE id = ?", (agent,)
        ).fetchone() is None:
            register(conn, Citizen(id=agent, display_name=agent.title()))
        return commissions.enqueue(conn, agent, body, at=when)


def kick_deferred_worker(
    *,
    app,
    agent: str,
    db_path: Path,
) -> None:
    """Drain this citizen's queue in the background (busy check off)."""

    def _run() -> None:
        try:
            with app.app_context():
                state = app.extensions.get("soveryn") or {}
                loops = state.get("agent_loops") or {}
                conv_store = state.get("conv_store")
                env = state.get("env")
                if not loops or conv_store is None:
                    logger.warning("deferred kick: loops/conv missing")
                    return
                from soveryn.citizens.runtime import (
                    drain_once,
                    make_agent_process_fn,
                )

                process_fn = make_agent_process_fn(
                    loops,
                    conv_store,
                    data_root=getattr(env, "data_root", None) if env is not None else None,
                )
                closed = drain_once(
                    db_path,
                    process_fn=process_fn,
                    worker="messages-deferred",
                    citizen_ids=[agent],
                    busy_fn=lambda _cid: False,
                    conv_store=conv_store,
                    data_root=getattr(env, "data_root", None) if env is not None else None,
                )
                if closed:
                    try:
                        from soveryn.platform.webpush.notify import notify_needs_you

                        notify_needs_you(
                            title=f"{agent.title()} finished",
                            body="Reply is in the thread.",
                            url=f"/messages/{agent}",
                            tag=f"deferred-{agent}",
                        )
                    except Exception:
                        logger.exception("deferred webpush failed")
        except Exception:
            logger.exception("deferred worker failed for %s", agent)

    threading.Thread(
        target=_run, name=f"deferred-{agent}", daemon=True
    ).start()


def try_defer_chat(
    *,
    agent: str,
    session_id: str,
    message: str,
    state: dict[str, Any],
) -> str | None:
    """Enqueue if we can. None means fall through to live SSE."""
    from soveryn.config.runtime import DEFERRED_CHAT_AGENTS

    if agent not in DEFERRED_CHAT_AGENTS:
        return None
    from flask import current_app

    if current_app.config.get("DEFER_CHAT") is False:
        return None
    conv = state.get("conv_store")
    if conv is None:
        return None
    session = conv.get_session(session_id)
    if session is None:
        return None
    import os

    configured = current_app.config.get("CITIZENS_DB") or os.environ.get(
        "SOVERYN_CITIZENS_DB"
    )
    db_path = Path(
        configured
        or (Path.home() / "soveryn_vnext" / "data" / "citizens.db")
    )
    if not db_path.exists():
        return None
    try:
        cid = enqueue_messages_turn(
            agent=agent,
            session_id=session_id,
            message=message,
            conv_store=conv,
            db_path=db_path,
        )
    except Exception:
        logger.exception("defer enqueue failed; streaming instead")
        return None
    kick_deferred_worker(
        app=current_app._get_current_object(), agent=agent, db_path=db_path
    )
    return cid
