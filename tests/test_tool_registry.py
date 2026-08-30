"""Tests for the platform-owned tool registry."""

import pytest

from soveryn.platform.telemetry import query
from soveryn.platform.tools.registry import (
    TOOL_AUDIT_SOURCE,
    TOOL_INVOKED_EVENT,
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

    with pytest.raises(ToolRegistryError, match="retired"):
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


def test_default_audit_hook_writes_success_to_telemetry(monkeypatch, tmp_path):
    monkeypatch.setenv("SOVERYN_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="echo",
        owner="aetheria",
        schema={"type": "object"},
        handler=lambda args: {"echo": args["text"]},
    ))

    registry.invoke("aetheria", "echo", {"text": "hello"})

    events = query({"source": TOOL_AUDIT_SOURCE, "event_type": TOOL_INVOKED_EVENT})
    assert len(events) == 1
    assert events[0].level == "info"
    assert events[0].payload == {
        "agent": "aetheria",
        "tool_name": "echo",
        "ok": True,
        "error": None,
    }


def test_default_audit_hook_writes_failure_to_telemetry(monkeypatch, tmp_path):
    monkeypatch.setenv("SOVERYN_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="explode",
        owner="scotty",
        schema={"type": "object"},
        handler=lambda args: (_ for _ in ()).throw(RuntimeError("boom")),
    ))

    with pytest.raises(RuntimeError, match="boom"):
        registry.invoke("scotty", "explode", {})

    events = query({"source": TOOL_AUDIT_SOURCE, "event_type": TOOL_INVOKED_EVENT})
    assert len(events) == 1
    assert events[0].level == "error"
    assert events[0].payload == {
        "agent": "scotty",
        "tool_name": "explode",
        "ok": False,
        "error": "RuntimeError: boom",
    }


def test_compatibility_shim_reexports_platform_registry_objects():
    from soveryn.tools import registry as compat
    from soveryn.platform.tools import registry as platform

    assert compat.ToolRegistry is platform.ToolRegistry
    assert compat.ToolSpec is platform.ToolSpec
    assert compat.ToolAuditEvent is platform.ToolAuditEvent
    assert compat.ToolArgError is platform.ToolArgError
    assert compat.ToolRegistryError is platform.ToolRegistryError


def test_iter_tools_for_agent_returns_only_that_owner():
    registry = ToolRegistry(active_agents=("aetheria", "vett"), audit_hook=None)
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    registry.register(ToolSpec(
        name="a1", owner="aetheria", schema=schema, handler=lambda args: None,
    ))
    registry.register(ToolSpec(
        name="a2", owner="aetheria", schema=schema, handler=lambda args: None,
    ))
    registry.register(ToolSpec(
        name="v1", owner="vett", schema=schema, handler=lambda args: None,
    ))
    aetheria_tools = registry.iter_tools_for_agent("aetheria")
    assert {spec.name for spec in aetheria_tools} == {"a1", "a2"}
    assert all(spec.owner == "aetheria" for spec in aetheria_tools)


def test_iter_tools_for_agent_normalizes_input():
    registry = ToolRegistry(active_agents=("aetheria",), audit_hook=None)
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    registry.register(ToolSpec(
        name="x", owner="aetheria", schema=schema, handler=lambda args: None,
    ))
    assert len(registry.iter_tools_for_agent("  AETHERIA  ")) == 1


def test_iter_tools_for_agent_empty_when_no_tools():
    registry = ToolRegistry(active_agents=("aetheria",), audit_hook=None)
    assert registry.iter_tools_for_agent("aetheria") == ()


def test_iter_tools_with_owners_returns_sorted_pairs():
    registry = ToolRegistry(active_agents=("aetheria", "vett"), audit_hook=None)
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    registry.register(ToolSpec(
        name="zulu", owner="vett", schema=schema, handler=lambda args: None,
    ))
    registry.register(ToolSpec(
        name="alpha", owner="aetheria", schema=schema, handler=lambda args: None,
    ))
    pairs = registry.iter_tools_with_owners()
    assert pairs == (("alpha", "aetheria"), ("zulu", "vett"))
