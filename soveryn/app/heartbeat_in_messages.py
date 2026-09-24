"""Fold Aetheria's heartbeat notes into the Messages DM.

Heartbeat writes to a session titled ``[heartbeat] aetheria``. Messages
refuses to open that session (it would steal the 1:1). Phone pings then
point at /messages/aetheria, which is the live DM — so the reflection
never appears. Merge recent assistant heartbeat notes into the DM history
for display only; the model still reads the DM session alone.
"""

from __future__ import annotations

from typing import Any

HEARTBEAT_SESSION_TITLE = "[heartbeat] aetheria"
_MAX_NOTES = 16


def fold_heartbeat_notes(
    conv,
    session,
    turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if session is None or getattr(session, "agent", None) != "aetheria":
        return list(turns)
    title = (getattr(session, "title", None) or "").strip()
    if title == HEARTBEAT_SESSION_TITLE:
        return list(turns)

    hb = None
    for s in conv.list_sessions(agent="aetheria", limit=80):
        if (s.title or "").strip() == HEARTBEAT_SESSION_TITLE:
            hb = s
            break
    if hb is None:
        return list(turns)

    seen = {(t.get("role"), t.get("content")) for t in turns}
    extra: list[dict[str, Any]] = []
    for t in conv.load_history(hb.session_id):
        if t.role != "assistant":
            continue
        body = (t.content or "").strip()
        if not body:
            continue
        row = {
            "role": "assistant",
            "content": t.content,
            "timestamp": t.timestamp,
            "source": "heartbeat",
        }
        key = (row["role"], row["content"])
        if key in seen:
            continue
        seen.add(key)
        extra.append(row)
    if not extra:
        return list(turns)
    extra = extra[-_MAX_NOTES:]
    merged = list(turns) + extra
    merged.sort(key=lambda r: r.get("timestamp") or "")
    return merged
