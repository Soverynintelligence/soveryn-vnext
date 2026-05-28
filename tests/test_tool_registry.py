"""Tests for the platform-owned tool registry."""

import pytest

from soveryn.platform.tools.registry import (
    ToolAuditEvent,
    ToolArgError,
    ToolRegistry,
    ToolRegistryError,
    ToolSpec,
)


def test_registered_schema_is_discoverable():
    registry = ToolRegistry()
    schema = {"type": "object", "properties": {"path": {"type": "string"}}}

    registry.register(ToolSpec(
        name="read_file",
        owner="scotty",
        schema=schema,
        handler=lambda args: args["path"],
    ))

    assert registry.schema_for("scotty", "read_file") == schema


def test_unregistered_tool_cannot_be_invoked():
    registry = ToolRegistry()

    with pytest.raises(ToolRegistryError, match="not registered"):
        registry.invoke("aetheria", "missing_tool", {})


def test_tool_registered_for_one_agent_cannot_be_invoked_by_another():
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="read_file",
        owner="scotty",
        schema={},
        handler=lambda args: "ok",
    ))

    with pytest.raises(ToolRegistryError, match="not registered"):
        registry.invoke("aetheria", "read_file", {})


def test_invalid_tool_args_raise_before_dispatch_and_emit_audit_event():
    events: list[ToolAuditEvent] = []
    handler_calls: list[dict] = []
    registry = ToolRegistry(audit_hook=events.append)
    registry.register(ToolSpec(
        name="read_file",
        owner="scotty",
        schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=lambda args: handler_calls.append(dict(args)),
    ))

    with pytest.raises(ToolArgError, match="'path' is a required property"):
        registry.invoke("scotty", "read_file", {})

    assert handler_calls == []
    assert events == [ToolAuditEvent(
        agent="scotty",
        tool_name="read_file",
        args={},
        ok=False,
        error="ToolArgError: 'path' is a required property",
    )]


def test_retired_or_unknown_agent_cannot_own_tool():
    registry = ToolRegistry()

    with pytest.raises(ToolRegistryError, match="not an active agent"):
        registry.register(ToolSpec(
            name="old_tool",
            owner="tinker",
            schema={},
            handler=lambda args: None,
        ))


def test_invoke_runs_handler_and_emits_audit_event():
    events: list[ToolAuditEvent] = []
    registry = ToolRegistry(audit_hook=events.append)
    registry.register(ToolSpec(
        name="echo",
        owner="aetheria",
        schema={"type": "object"},
        handler=lambda args: {"echo": args["text"]},
    ))

    result = registry.invoke("aetheria", "echo", {"text": "hello"})

    assert result == {"echo": "hello"}
    assert events == [ToolAuditEvent(
        agent="aetheria",
        tool_name="echo",
        args={"text": "hello"},
        ok=True,
        result={"echo": "hello"},
    )]


def test_compatibility_shim_reexports_platform_registry_objects():
    from soveryn.tools import registry as compat
    from soveryn.platform.tools import registry as platform

    assert compat.ToolRegistry is platform.ToolRegistry
    assert compat.ToolSpec is platform.ToolSpec
    assert compat.ToolAuditEvent is platform.ToolAuditEvent
    assert compat.ToolRegistryError is platform.ToolRegistryError
