"""Tests for Aetheria package entry surfaces."""

import pytest

from soveryn.agents.aetheria.chat_surface import AetheriaChatSurface, ChatSurfaceState
from soveryn.agents.aetheria.heartbeat_surface import (
    AetheriaHeartbeatSurface,
    HeartbeatNotPortedError,
    HeartbeatSurfaceState,
)
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


def test_chat_and_heartbeat_surfaces_do_not_share_mutable_state():
    chat_state = ChatSurfaceState()
    heartbeat_state = HeartbeatSurfaceState()
    chat_state.metadata["surface"] = "chat"
    heartbeat_state.metadata["surface"] = "heartbeat"

    assert chat_state.metadata == {"surface": "chat"}
    assert heartbeat_state.metadata == {"surface": "heartbeat"}
    assert chat_state.metadata is not heartbeat_state.metadata
    assert not hasattr(chat_state, "ticks_seen")
    assert not hasattr(heartbeat_state, "turns_seen")


def test_heartbeat_surface_is_declared_but_not_ported():
    state = HeartbeatSurfaceState()
    surface = AetheriaHeartbeatSurface(state=state)

    with pytest.raises(HeartbeatNotPortedError, match="declared, not ported"):
        surface.tick()

    assert state.ticks_seen == 1
