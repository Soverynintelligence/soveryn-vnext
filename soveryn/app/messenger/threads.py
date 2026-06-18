"""Thread management. A messenger Thread is a ConversationStore Session
with extra metadata (agent binding, mute flag, auto-title).

Per spec §4.2: per-thread agent binding is immutable. Creating a thread
binds it to one agent; switching agents = new thread.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.memory.conversation_store import ConversationStore
from soveryn.app.messenger.store import MessengerStore


VALID_AGENTS = tuple(ACTIVE_AGENTS)


class ThreadError(Exception):
    pass


@dataclass(frozen=True)
class Thread:
    thread_id: str
    user_id: str
    agent: str
    session_id: str
    title: str
    created_at: str
    last_activity: str
    muted: bool


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auto_title(agent: str) -> str:
    """Friendly default title when caller didn't supply one."""
    # E.g. "Aetheria — Sat Jun 14"
    when = datetime.now().strftime("%a %b %d")
    return f"{agent.capitalize()} — {when}"


def create_thread(
    messenger_store: MessengerStore,
    conv_store: ConversationStore,
    *,
    user_id: str,
    agent: str,
    title: Optional[str] = None,
) -> Thread:
    """Create a new thread + its backing ConversationStore Session."""
    if agent not in VALID_AGENTS:
        raise ThreadError(
            f"invalid agent: {agent!r}; must be one of {VALID_AGENTS}"
        )
    thread_id = str(uuid.uuid4())
    actual_title = title or _auto_title(agent)
    session_id = conv_store.new_session(agent, title=f"[m] {actual_title}")
    now = _now_iso()
    with messenger_store._conn() as con:
        con.execute(
            "INSERT INTO m_threads (thread_id, user_id, agent, session_id, title, "
            "created_at, last_activity, muted) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (thread_id, user_id, agent, session_id, actual_title, now, now),
        )
    return Thread(
        thread_id=thread_id,
        user_id=user_id,
        agent=agent,
        session_id=session_id,
        title=actual_title,
        created_at=now,
        last_activity=now,
        muted=False,
    )


def get_thread(
    messenger_store: MessengerStore, *, thread_id: str,
) -> Optional[Thread]:
    with messenger_store._conn() as con:
        row = con.execute(
            "SELECT * FROM m_threads WHERE thread_id=?", (thread_id,),
        ).fetchone()
    if row is None:
        return None
    return Thread(
        thread_id=row["thread_id"],
        user_id=row["user_id"],
        agent=row["agent"],
        session_id=row["session_id"],
        title=row["title"],
        created_at=row["created_at"],
        last_activity=row["last_activity"],
        muted=bool(row["muted"]),
    )


def list_threads(
    messenger_store: MessengerStore, *, user_id: str,
) -> list[Thread]:
    with messenger_store._conn() as con:
        rows = con.execute(
            "SELECT * FROM m_threads WHERE user_id=? ORDER BY last_activity DESC",
            (user_id,),
        ).fetchall()
    return [
        Thread(
            thread_id=r["thread_id"],
            user_id=r["user_id"],
            agent=r["agent"],
            session_id=r["session_id"],
            title=r["title"],
            created_at=r["created_at"],
            last_activity=r["last_activity"],
            muted=bool(r["muted"]),
        )
        for r in rows
    ]


def set_thread_muted(
    messenger_store: MessengerStore, *, thread_id: str, muted: bool,
) -> None:
    with messenger_store._conn() as con:
        con.execute(
            "UPDATE m_threads SET muted=? WHERE thread_id=?",
            (1 if muted else 0, thread_id),
        )


def touch_thread(messenger_store: MessengerStore, *, thread_id: str) -> None:
    """Bump last_activity. Called after each inbound or outbound message."""
    with messenger_store._conn() as con:
        con.execute(
            "UPDATE m_threads SET last_activity=? WHERE thread_id=?",
            (_now_iso(), thread_id),
        )
