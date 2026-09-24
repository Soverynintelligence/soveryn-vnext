"""Request-scoped room/DM context for tool handlers (house_post → Messaged chip)."""

from __future__ import annotations

from contextvars import ContextVar

# Set by /chat and /chat_stream when Jon is in a 1:1 (or room) session.
dm_session_id: ContextVar[str | None] = ContextVar("room_dm_session_id", default=None)
room_session_id: ContextVar[str | None] = ContextVar("room_session_id", default=None)
data_root: ContextVar[str | None] = ContextVar("room_data_root", default=None)
