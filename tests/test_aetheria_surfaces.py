"""Tests for Aetheria package entry surfaces."""

import pytest

from soveryn.agents.aetheria.chat_surface import AetheriaChatSurface, ChatSurfaceState
from soveryn.agents.aetheria.persona import AETHERIA_PERSONA as AETHERIA_PERSONA_SOURCE
from soveryn.agents.aetheria import recall_policy
from soveryn.agents.personas import AETHERIA_PERSONA as AETHERIA_PERSONA_COMPAT
from soveryn.agents import recall as recall_compat


class _FakeAetheriaLoop:
    agent_name = "aetheria"

    def __init__(self) -> None:
        self.calls = []

    def process_message(self, session_id: str, message: str):
        self.calls.append((session_id, message))
        return {"ok": True, "message": message}


def test_aetheria_persona_is_sourced_from_aetheria_package():
    assert AETHERIA_PERSONA_COMPAT is AETHERIA_PERSONA_SOURCE


def test_recall_compatibility_shim_reexports_aetheria_policy():
    assert recall_compat.format_recall_context is recall_policy.format_recall_context
    assert recall_compat.MAX_CONTENT_CHARS_PER_NODE == recall_policy.MAX_CONTENT_CHARS_PER_NODE


def test_chat_surface_rejects_non_aetheria_loop():
    class _OtherLoop:
        agent_name = "vett"

    with pytest.raises(ValueError, match="aetheria"):
        AetheriaChatSurface(_OtherLoop())


def test_chat_surface_delegates_to_loop_and_tracks_own_state():
    loop = _FakeAetheriaLoop()
    state = ChatSurfaceState()
    surface = AetheriaChatSurface(loop, state=state)

    result = surface.process_message("sid-1", "hello")

    assert result == {"ok": True, "message": "hello"}
    assert loop.calls == [("sid-1", "hello")]
    assert state.turns_seen == 1
