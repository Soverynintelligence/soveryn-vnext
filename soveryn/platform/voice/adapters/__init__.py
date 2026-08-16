"""Voice agent adapters — plug house brains into the duplex shell."""

from soveryn.platform.voice.adapters.agent_loop import AgentLoopAdapter
from soveryn.platform.voice.adapters.base import (
    AgentAdapter,
    AgentAdapterBase,
    AgentTextChunk,
)

__all__ = [
    "AgentAdapter",
    "AgentAdapterBase",
    "AgentLoopAdapter",
    "AgentTextChunk",
]
