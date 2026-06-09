"""Cross-Surface Continuity — paired-turn extraction (data layer).

Queries OTHER aetheria sessions inside the configured window, filters
autonomous prefixes (Signal stays), and extracts the last N paired
user/assistant turns per session. The brief renderer (Task 4) formats;
this module only produces the structured data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from soveryn.memory.conversation_store import ConversationStore, Turn
from soveryn.platform.continuity.config import ContinuityConfig


DEFAULT_PER_SESSION_PAIRS = 3


@dataclass(frozen=True)
class PairedTurn:
    user: str
    assistant: str | None  # None when the user turn has no reply yet (in-flight)


@dataclass(frozen=True)
class SessionTail:
    session_id: str
    title: str | None
    updated_at: str
    paired_turns: tuple[PairedTurn, ...]


def _extract_paired_turns(
    history: tuple[Turn, ...], *, n: int
) -> tuple[PairedTurn, ...]:
    """Walk history left-to-right, pair user→assistant, return the last n.

    Ignores tool/system rows entirely. An orphan user with no following
    assistant becomes an in-flight pair (assistant=None). An orphan
    assistant with no preceding user is skipped defensively.
    """
    pairs: list[PairedTurn] = []
    pending: str | None = None
    for turn in history:
        if turn.role == "user":
            if pending is not None:
                # Previous user had no assistant reply — record as in-flight
                pairs.append(PairedTurn(user=pending, assistant=None))
            pending = turn.content
        elif turn.role == "assistant":
            if pending is not None:
                pairs.append(PairedTurn(user=pending, assistant=turn.content))
                pending = None
            # else: orphan assistant, skip
        # tool / system: ignore
    if pending is not None:
        pairs.append(PairedTurn(user=pending, assistant=None))
    if n <= 0:
        return ()
    return tuple(pairs[-n:])


def recent_cross_session_tails(
    conv_store: ConversationStore,
    *,
    agent: str,
    current_session_id: str,
    config: ContinuityConfig,
    per_session_pairs: int = DEFAULT_PER_SESSION_PAIRS,
) -> tuple[SessionTail, ...]:
    """Return the last paired turns from OTHER recent sessions for `agent`.

    Skips autonomous sessions per `config.session_is_autonomous` (Signal
    passes that filter intentionally). Sessions that produce zero paired
    turns are omitted. Ordering matches the underlying query — newest
    first by updated_at.
    """
    since = datetime.now() - timedelta(hours=config.window_hours)
    sessions = conv_store.list_sessions_with_recent_activity(
        agent=agent,
        since=since,
        exclude_session_id=current_session_id,
    )
    tails: list[SessionTail] = []
    for session in sessions:
        if config.session_is_autonomous(session.title):
            continue
        history = conv_store.load_history(session.session_id)
        paired = _extract_paired_turns(history, n=per_session_pairs)
        if not paired:
            continue
        tails.append(
            SessionTail(
                session_id=session.session_id,
                title=session.title,
                updated_at=session.updated_at,
                paired_turns=paired,
            )
        )
    return tuple(tails)
