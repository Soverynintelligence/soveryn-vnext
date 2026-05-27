"""Platform-owned tool registry for SOVERYN vNext.

This module defines the narrow mechanism boundary for tool capability lookup and
mediated execution. It is intentionally small in Phase 1: schema validation,
permission tiers, and durable telemetry are represented by explicit shapes but
implemented in later platform tasks.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from soveryn.config.runtime import ACTIVE_AGENTS

ToolHandler = Callable[[Mapping[str, Any]], Any]
AuditHook = Callable[["ToolAuditEvent"], None]


class ToolRegistryError(LookupError):
    """Raised when a tool cannot be registered or invoked."""


@dataclass(frozen=True)
class ToolSpec:
    """Declarative registration record for one agent-owned tool."""

    name: str
    owner: str
    schema: Mapping[str, Any]
    handler: ToolHandler
    description: str = ""


@dataclass(frozen=True)
class ToolAuditEvent:
    """Structured audit shape emitted around mediated tool execution."""

    agent: str
    tool_name: str
    args: Mapping[str, Any]
    ok: bool
    result: Any = None
    error: str | None = None


class ToolRegistry:
    """In-memory registry of agent tool capabilities.

    Registration confers capability. A tool registered for one agent cannot be
    invoked by another agent through this registry.
    """

    def __init__(
        self,
        *,
        active_agents: tuple[str, ...] = ACTIVE_AGENTS,
        audit_hook: AuditHook | None = None,
    ) -> None:
        self._active_agents = frozenset(active_agents)
        self._audit_hook = audit_hook
        self._tools: dict[tuple[str, str], ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        owner = _normalize(spec.owner)
        name = _normalize(spec.name)
        if owner not in self._active_agents:
            raise ToolRegistryError(f"Tool owner {owner!r} is not an active agent")
        key = (owner, name)
        if key in self._tools:
            raise ToolRegistryError(f"Tool {name!r} is already registered for {owner!r}")
        self._tools[key] = ToolSpec(
            name=name,
            owner=owner,
            schema=dict(spec.schema),
            handler=spec.handler,
            description=spec.description,
        )

    def schema_for(self, agent: str, tool_name: str) -> Mapping[str, Any]:
        return dict(self._lookup(agent, tool_name).schema)

    def invoke(self, agent: str, tool_name: str, args: Mapping[str, Any]) -> Any:
        spec = self._lookup(agent, tool_name)
        try:
            result = spec.handler(dict(args))
        except Exception as exc:
            self._emit(ToolAuditEvent(
                agent=spec.owner,
                tool_name=spec.name,
                args=dict(args),
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            ))
            raise
        self._emit(ToolAuditEvent(
            agent=spec.owner,
            tool_name=spec.name,
            args=dict(args),
            ok=True,
            result=result,
        ))
        return result

    def _lookup(self, agent: str, tool_name: str) -> ToolSpec:
        key = (_normalize(agent), _normalize(tool_name))
        try:
            return self._tools[key]
        except KeyError as exc:
            raise ToolRegistryError(
                f"Tool {key[1]!r} is not registered for agent {key[0]!r}"
            ) from exc

    def _emit(self, event: ToolAuditEvent) -> None:
        if self._audit_hook is not None:
            self._audit_hook(event)


def _normalize(value: str) -> str:
    normalized = value.lower().strip()
    if not normalized:
        raise ToolRegistryError("Tool registry names cannot be blank")
    return normalized
