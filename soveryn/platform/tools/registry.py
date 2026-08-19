"""Platform-owned tool registry for SOVERYN vNext.

This module defines the narrow mechanism boundary for tool capability lookup and
mediated execution.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError, validate

from soveryn.config.runtime import ACTIVE_AGENTS

ToolHandler = Callable[[Mapping[str, Any]], Any]
AuditHook = Callable[["ToolAuditEvent"], None]
TOOL_AUDIT_SOURCE = "platform.tools.registry"
TOOL_INVOKED_EVENT = "tool.invoked"


class ToolRegistryError(LookupError):
    """Raised when a tool cannot be registered or invoked."""


class ToolArgError(ValueError):
    """Raised when tool invocation arguments fail schema validation."""


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
        # Default: Continuum ledger + telemetry — quiet tool failures become
        # visible truth events (timeouts / soft errors), not silence.
        if audit_hook is None:
            from soveryn.platform.acttruth.hooks import acttruth_and_telemetry_audit_hook

            self._audit_hook = acttruth_and_telemetry_audit_hook
        else:
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

    def iter_tools_for_agent(self, agent: str) -> tuple[ToolSpec, ...]:
        """Return every tool registered for one owner, in insertion order."""

        normalized = _normalize(agent)
        return tuple(
            spec for (owner, _name), spec in self._tools.items()
            if owner == normalized
        )

    def iter_tools_with_owners(self) -> tuple[tuple[str, str], ...]:
        """Return (tool_name, owner_agent) pairs sorted by tool name."""

        return tuple(sorted((spec.name, spec.owner) for spec in self._tools.values()))

    def invoke(self, agent: str, tool_name: str, args: Mapping[str, Any]) -> Any:
        spec = self._lookup(agent, tool_name)
        invocation_args = dict(args)
        try:
            validate(instance=invocation_args, schema=dict(spec.schema))
        except ValidationError as exc:
            error = f"ToolArgError: {exc.message}"
            self._emit(ToolAuditEvent(
                agent=spec.owner,
                tool_name=spec.name,
                args=invocation_args,
                ok=False,
                error=error,
            ))
            raise ToolArgError(exc.message) from exc
        try:
            result = spec.handler(invocation_args)
        except Exception as exc:
            self._emit(ToolAuditEvent(
                agent=spec.owner,
                tool_name=spec.name,
                args=invocation_args,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            ))
            raise
        self._emit(ToolAuditEvent(
            agent=spec.owner,
            tool_name=spec.name,
            args=invocation_args,
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


def telemetry_audit_hook(event: ToolAuditEvent) -> None:
    """Persist tool invocation audits to the platform telemetry store."""

    from soveryn.platform import telemetry

    telemetry.log(
        source=TOOL_AUDIT_SOURCE,
        event_type=TOOL_INVOKED_EVENT,
        level="info" if event.ok else "error",
        payload={
            "agent": event.agent,
            "tool_name": event.tool_name,
            "ok": event.ok,
            "error": event.error,
        },
    )


def _normalize(value: str) -> str:
    normalized = value.lower().strip()
    if not normalized:
        raise ToolRegistryError("Tool registry names cannot be blank")
    return normalized
