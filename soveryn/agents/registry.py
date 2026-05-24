"""SOVERYN vNext — agent registry.

Registers AgentLoop instances by name. Rejects any name in RETIRED at
registration time so retired agents can't slip back in by accident
(spec §10 Bucket C).

Pure registry — no AgentLoop implementation yet; that comes in a later step.
The registry takes any object as the "agent" so this module can be tested
in isolation without dragging in the inference layer.
"""

from __future__ import annotations
from typing import Any, Iterator

from soveryn.config.runtime import ACTIVE_AGENTS, RETIRED


class AgentRegistryError(Exception):
    """Raised when registry invariants are violated."""


class AgentRegistry:
    """Per-process map from agent name to whatever object handles its work.

    The registry does NOT construct agents — callers build their own and
    register them. The registry's job is to enforce the active/retired
    contract from soveryn.config.runtime so the rest of the system can
    trust that `registry.get("scout")` never silently succeeds.
    """

    def __init__(self) -> None:
        self._agents: dict[str, Any] = {}

    def register(self, name: str, agent: Any) -> None:
        """Register an agent under `name`. Idempotent on identical re-registration; raises on conflict."""
        name = name.lower().strip()
        if not name:
            raise AgentRegistryError("Agent name must be non-empty")
        if name in RETIRED:
            raise AgentRegistryError(
                f"Refusing to register {name!r}: retired (spec §10 Bucket C)"
            )
        if name not in ACTIVE_AGENTS:
            raise AgentRegistryError(
                f"Refusing to register {name!r}: not in ACTIVE_AGENTS "
                f"({ACTIVE_AGENTS}). If this is a new agent, add it to "
                f"soveryn.config.runtime.ACTIVE_AGENTS first."
            )
        existing = self._agents.get(name)
        if existing is not None and existing is not agent:
            raise AgentRegistryError(
                f"Agent {name!r} already registered with a different instance"
            )
        self._agents[name] = agent

    def get(self, name: str) -> Any:
        """Return the registered agent. Raises KeyError if absent."""
        name = name.lower().strip()
        if name in RETIRED:
            raise AgentRegistryError(
                f"{name!r} is retired; no lookup possible (spec §10)"
            )
        return self._agents[name]

    def has(self, name: str) -> bool:
        return name.lower().strip() in self._agents

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._agents))

    def __iter__(self) -> Iterator[tuple[str, Any]]:
        return iter(sorted(self._agents.items()))

    def __len__(self) -> int:
        return len(self._agents)
