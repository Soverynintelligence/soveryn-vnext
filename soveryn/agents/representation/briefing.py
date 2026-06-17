"""Briefing assembly for the representation daemon.

Gathers:
  1. Recent user/assistant turns for the owner agent (across recent non-autonomous
     sessions) up to `turns_per_briefing`, each rendered with a stable synthetic id.
  2. Existing 'conclusion' lattice nodes for this subject, each rendered with
     its real node uuid.

Turn-id scheme: ``turn:<session_id>:<0-based-index-in-full-history>``

Example briefing line:
    [node:turn:abc123:0] user: What motivates Jon?

The index is the position of the turn in the full ordered history returned by
``conv_store.load_history(session_id)`` (ORDER BY rowid ASC). This is stable
within a session and greppable — running the same daemon pass twice produces
the same ids for unchanged history. The session_id is the UUID in
conversation_meta, so the id is globally unique within the owner's sessions.

Premise citations in conclusions will reference these ids, allowing the
writeback layer to validate that cited nodes actually exist in source_node_ids.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.lattice.legacy import LatticeStore

logger = logging.getLogger(__name__)

# How far back to scan for recent sessions.  Wide enough to always catch the
# last meaningful activity; the daemon tick interval is ~15 min so 72 h gives
# plenty of headroom without pulling ancient history.
_LOOKBACK_HOURS = 72

# Sentinel — briefing has no "current session" to exclude, so we use an empty
# string which can never match a real UUID.
_NO_CURRENT_SESSION = ""

# Prefixes that mark an autonomous / daemon session.  Matches the filter in
# the continuity layer (store.py recent_cross_session_tails).
_AUTONOMOUS_PREFIXES = ("⚙️", "🤖", "[daemon]", "[ares]", "[signal]")


def _is_autonomous(title: str | None) -> bool:
    if not title:
        return False
    lower = title.lower()
    return any(lower.startswith(p.lower()) for p in _AUTONOMOUS_PREFIXES)


def build_briefing(
    conv_store: ConversationStore,
    lattice_store: LatticeStore,
    *,
    owner_agent: str,
    subject: str,
    turns_per_briefing: int,
) -> tuple[str, str, list[str]]:
    """Assemble a briefing for the representation reasoning pass.

    Returns:
        briefing_text         — recent turns, each ``[node:<id>] <role>: <content>``
        prior_conclusions_text — existing conclusion nodes for `subject`,
                                 each ``[node:<node_id>] <content>``
        source_node_ids       — all ids referenced above (turn ids + conclusion ids)
    """
    # ── 1. Gather recent turns ─────────────────────────────────────────────────
    since = datetime.now() - timedelta(hours=_LOOKBACK_HOURS)
    try:
        sessions = conv_store.list_sessions_with_recent_activity(
            agent=owner_agent,
            since=since,
            exclude_session_id=_NO_CURRENT_SESSION,
        )
    except Exception:
        logger.exception("briefing: failed to list sessions for agent=%s", owner_agent)
        sessions = ()

    # Collect all user/assistant turns across non-autonomous sessions,
    # preserving insertion order (newest session first from the query, but
    # we'll flatten and take the last N overall so order within each session
    # must be preserved).  We build a flat list of (turn_id, role, content)
    # across all sessions, then cap to turns_per_briefing most-recent.
    all_turns: list[tuple[str, str, str]] = []  # (id, role, content)

    for session in sessions:
        if _is_autonomous(session.title):
            continue
        try:
            history = conv_store.load_history(session.session_id)
        except Exception:
            logger.exception(
                "briefing: failed to load history for session=%s", session.session_id
            )
            continue

        for idx, turn in enumerate(history):
            if turn.role not in ("user", "assistant"):
                continue
            turn_id = f"turn:{session.session_id}:{idx}"
            all_turns.append((turn_id, turn.role, turn.content))

    # The sessions query returns newest-first; within each session history is
    # oldest-first.  To get the most-recent N turns overall we take the tail
    # of the flat list (which is: oldest session's turns first, newest last).
    # We need to reverse the session ordering so we process oldest→newest
    # before capping.  Rebuild with sessions in chronological order.
    #
    # Actually: sessions are newest-first so all_turns currently has the
    # newest session's turns FIRST.  Reversing gives chronological order so
    # tail-slicing captures the most recent turns.
    all_turns_chrono = list(reversed(all_turns))
    capped = all_turns_chrono[-turns_per_briefing:] if turns_per_briefing > 0 else []

    briefing_lines: list[str] = []
    turn_ids: list[str] = []
    for turn_id, role, content in capped:
        briefing_lines.append(f"[node:{turn_id}] {role}: {content}")
        turn_ids.append(turn_id)

    briefing_text = "\n".join(briefing_lines)

    # ── 2. Gather prior conclusions for this subject ───────────────────────────
    try:
        all_nodes = lattice_store.iter_nodes(agent=owner_agent, include_library=False)
    except Exception:
        logger.exception(
            "briefing: failed to iter nodes for agent=%s", owner_agent
        )
        all_nodes = ()

    prior_lines: list[str] = []
    conclusion_ids: list[str] = []
    for node in all_nodes:
        if node.type != "conclusion":
            continue
        prov = node.provenance or {}
        if prov.get("subject") != subject:
            continue
        prior_lines.append(f"[node:{node.id}] {node.content}")
        conclusion_ids.append(node.id)

    prior_conclusions_text = "\n".join(prior_lines)

    # ── 3. Collect all source ids ──────────────────────────────────────────────
    source_node_ids: list[str] = turn_ids + conclusion_ids

    return briefing_text, prior_conclusions_text, source_node_ids
