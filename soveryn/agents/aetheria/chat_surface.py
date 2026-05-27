"""Aetheria chat entry surface.

This module names the chat-facing entry point separately from heartbeat. It wraps
the existing AgentLoop behavior without moving or rewriting that behavior in
Phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from soveryn.agents.loop import AgentLoop
from soveryn.inference.llama_server_client import ChatResponse


@dataclass
class ChatSurfaceState:
    """Mutable state owned by the chat surface only."""

    turns_seen: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class AetheriaChatSurface:
    """Thin entry point over Aetheria's existing AgentLoop chat behavior."""

    def __init__(self, loop: AgentLoop, state: ChatSurfaceState | None = None) -> None:
        if loop.agent_name != "aetheria":
            raise ValueError("AetheriaChatSurface requires an AgentLoop for 'aetheria'")
        self.loop = loop
        self.state = state or ChatSurfaceState()

    def process_message(self, session_id: str, message: str) -> ChatResponse:
        self.state.turns_seen += 1
        return self.loop.process_message(session_id, message)
