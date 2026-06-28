"""Aetheria-facing ToolSpecs for Project Sandbox."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.sandbox.engine import SandboxEngine, SandboxError
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def build_sandbox_get_status_tool(*, engine: SandboxEngine, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        return engine.get_status(run_id=_optional_str(args, "run_id"))

    return ToolSpec(
        name="sandbox_get_status",
        owner=owner_agent,
        schema=_run_id_schema(),
        handler=handler,
        description=(
            "Return the current Project Sandbox station state: resources, cycle, "
            "alerts, active research, discovered rules, persona flags, and "
            "persona-shaped perception notes."
        ),
    )


def build_sandbox_list_actions_tool(*, engine: SandboxEngine, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        return engine.list_actions(run_id=_optional_str(args, "run_id"))

    return ToolSpec(
        name="sandbox_list_actions",
        owner=owner_agent,
        schema=_run_id_schema(),
        handler=handler,
        description=(
            "List Project Sandbox actions and research topics. Actions include "
            "availability, resource requirements, and known effects only after "
            "Aetheria has discovered those rules by play."
        ),
    )


def build_sandbox_execute_action_tool(*, engine: SandboxEngine, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        action_id = args.get("action_id", "")
        if not isinstance(action_id, str) or not action_id.strip():
            raise ToolArgError("action_id must be a non-empty string")
        try:
            return engine.execute_action(action_id.strip(), run_id=_optional_str(args, "run_id"))
        except SandboxError as exc:
            raise ToolArgError(str(exc)) from exc

    return ToolSpec(
        name="sandbox_execute_action",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "action_id": {
                    "type": "string",
                    "description": "Action id from sandbox_list_actions.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Optional run id. Omit to use the default station-alpha run.",
                },
            },
            "required": ["action_id"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Execute one deterministic Project Sandbox action. Returns previous "
            "resources, new resources, observed deltas, alerts, and any newly "
            "discovered rule."
        ),
    )


def build_sandbox_research_tool(*, engine: SandboxEngine, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        topic = args.get("topic", "")
        if not isinstance(topic, str) or not topic.strip():
            raise ToolArgError("topic must be a non-empty string")
        try:
            return engine.research(topic.strip(), run_id=_optional_str(args, "run_id"))
        except SandboxError as exc:
            raise ToolArgError(str(exc)) from exc

    return ToolSpec(
        name="sandbox_research",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Research topic from sandbox_list_actions.research_topics.",
                },
                "run_id": {
                    "type": "string",
                    "description": "Optional run id. Omit to use the default station-alpha run.",
                },
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Start one background Project Sandbox research process. Research costs "
            "resources immediately and completes after future action cycles, "
            "revealing rules, archives, or persona shifts."
        ),
    )


def register_sandbox_tools(
    registry: ToolRegistry,
    *,
    sandbox_root: Path,
    owner_agent: str = "aetheria",
) -> SandboxEngine:
    engine = SandboxEngine(sandbox_root)
    registry.register(build_sandbox_get_status_tool(engine=engine, owner_agent=owner_agent))
    registry.register(build_sandbox_list_actions_tool(engine=engine, owner_agent=owner_agent))
    registry.register(build_sandbox_execute_action_tool(engine=engine, owner_agent=owner_agent))
    registry.register(build_sandbox_research_tool(engine=engine, owner_agent=owner_agent))
    return engine


def _run_id_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Optional run id. Omit to use the default station-alpha run.",
            },
        },
        "required": [],
        "additionalProperties": False,
    }


def _optional_str(args: Mapping[str, Any], key: str) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ToolArgError(f"{key} must be a non-empty string when provided")
    return value.strip()
