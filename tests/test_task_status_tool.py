"""TDD tests for soveryn.platform.delegation.tools — task_status tool.

Strict TDD order: tests written first, implementation second.

Run before implementing to confirm RED:
  ~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_task_status_tool.py -q
"""

from __future__ import annotations

import pytest

from soveryn.platform.delegation.store import DelegationStore
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path):
    return DelegationStore(tmp_path / "delegation_test.db")


def _make_registry():
    return ToolRegistry(active_agents=("aetheria",), audit_hook=lambda e: None)


def _dispatch(store: DelegationStore, *, objective: str = "Fix something") -> str:
    """Create a task in the store and return its id."""
    return store.create_task(
        dispatched_by="aetheria",
        objective=objective,
        scope="soveryn/x.py only",
        acceptance="pytest tests/test_x.py -q",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return _make_store(tmp_path)


@pytest.fixture
def registry():
    return _make_registry()


# ---------------------------------------------------------------------------
# 1. build_task_status_tool — name, owner, schema shape
# ---------------------------------------------------------------------------

def test_task_status_tool_name_and_owner(store):
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)
    assert tool.name == "task_status"
    assert tool.owner == "aetheria"


def test_task_status_schema_no_required_fields(store):
    """Schema should have no required fields — task_id is optional."""
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)
    schema = tool.schema
    assert schema.get("required", []) == [] or "required" not in schema
    assert schema.get("additionalProperties") is False


def test_task_status_schema_has_task_id_property(store):
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)
    props = tool.schema.get("properties", {})
    assert "task_id" in props
    assert props["task_id"].get("type") == "string"


# ---------------------------------------------------------------------------
# 2. With task_id — returns that task's status, objective, summary,
#    review_feedback
# ---------------------------------------------------------------------------

def test_with_task_id_returns_status_fields(store):
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)
    task_id = _dispatch(store, objective="Add docstring to fetcher.py")

    result = tool.handler({"task_id": task_id})

    assert result["id"] == task_id
    assert result["status"] == "dispatched"
    assert result["objective"] == "Add docstring to fetcher.py"
    # summary and review_feedback start as None for a fresh task
    assert "summary" in result
    assert "review_feedback" in result


def test_with_task_id_reflects_updated_status(store):
    """Status in result must track whatever is actually in the store."""
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)
    task_id = _dispatch(store)
    store.set_status(task_id, "executing")

    result = tool.handler({"task_id": task_id})
    assert result["status"] == "executing"


def test_with_task_id_includes_summary_when_set(store):
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)
    task_id = _dispatch(store)
    store.set_status(task_id, "executing")
    store.set_result(task_id, diff="some diff", test_output="ok", summary="Implemented feature X")
    store.set_status(task_id, "in_review")

    result = tool.handler({"task_id": task_id})
    assert result["summary"] == "Implemented feature X"


def test_with_task_id_includes_review_feedback_when_set(store):
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)
    task_id = _dispatch(store)
    store.set_status(task_id, "executing")
    store.set_result(task_id, diff="d", test_output="ok", summary="s")
    store.set_status(task_id, "in_review")
    store.set_review(task_id, review_feedback="LGTM — merge it")

    result = tool.handler({"task_id": task_id})
    assert result["review_feedback"] == "LGTM — merge it"


# ---------------------------------------------------------------------------
# 3. Unknown task_id → {error: "not_found", task_id: ...}
# ---------------------------------------------------------------------------

def test_unknown_task_id_returns_not_found(store):
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)

    result = tool.handler({"task_id": "does-not-exist-abc123"})
    assert result["error"] == "not_found"
    assert result["task_id"] == "does-not-exist-abc123"


def test_not_found_has_no_spurious_status(store):
    """The not_found result should NOT include a status field — avoids soft confabulation."""
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)

    result = tool.handler({"task_id": "ghost-id"})
    assert "status" not in result


# ---------------------------------------------------------------------------
# 4. No task_id → list open (non-terminal) tasks only, newest-first
# ---------------------------------------------------------------------------

def test_no_args_lists_open_tasks(store):
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)

    t1 = _dispatch(store, objective="Task one")
    t2 = _dispatch(store, objective="Task two")

    result = tool.handler({})
    ids = [item["id"] for item in result]
    assert t1 in ids
    assert t2 in ids


def test_no_args_excludes_terminal_tasks(store):
    """landed, rejected, failed tasks must NOT appear in the open-task list."""
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)

    open_id = _dispatch(store, objective="Still running")

    landed_id = _dispatch(store, objective="Will land")
    store.set_status(landed_id, "executing")
    store.set_result(landed_id, diff="d", test_output="ok", summary="s")
    store.set_status(landed_id, "in_review")
    store.set_status(landed_id, "landed")

    rejected_id = _dispatch(store, objective="Will be rejected")
    store.set_status(rejected_id, "executing")
    store.set_result(rejected_id, diff="d", test_output="fail", summary="s")
    store.set_status(rejected_id, "in_review")
    store.set_status(rejected_id, "rejected")

    failed_id = _dispatch(store, objective="Will fail")
    store.set_status(failed_id, "failed")

    result = tool.handler({})
    ids = [item["id"] for item in result]

    assert open_id in ids
    assert landed_id not in ids
    assert rejected_id not in ids
    assert failed_id not in ids


def test_no_args_includes_all_open_statuses(store):
    """dispatched, executing, in_review must all appear in the open list."""
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)

    dispatched_id = _dispatch(store, objective="Still dispatched")
    executing_id = _dispatch(store, objective="Now executing")
    store.set_status(executing_id, "executing")
    in_review_id = _dispatch(store, objective="In review")
    store.set_status(in_review_id, "executing")
    store.set_result(in_review_id, diff="d", test_output="ok", summary="s")
    store.set_status(in_review_id, "in_review")

    result = tool.handler({})
    ids = [item["id"] for item in result]

    assert dispatched_id in ids
    assert executing_id in ids
    assert in_review_id in ids


def test_no_args_each_item_has_id_status_objective(store):
    """Each item in the list must have at minimum: id, status, objective."""
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)

    _dispatch(store, objective="Check structure")
    result = tool.handler({})

    assert len(result) >= 1
    for item in result:
        assert "id" in item
        assert "status" in item
        assert "objective" in item


def test_no_args_returns_list(store):
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)
    result = tool.handler({})
    assert isinstance(result, list)


def test_no_args_empty_when_no_open_tasks(store):
    """When all tasks are terminal, the open list is empty."""
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)

    t = _dispatch(store, objective="Goes terminal")
    store.set_status(t, "failed")

    result = tool.handler({})
    assert result == []


# ---------------------------------------------------------------------------
# 5. The honesty invariant — a landed task reports exactly "landed"
# ---------------------------------------------------------------------------

def test_honesty_invariant_landed_task_reports_landed(store):
    """A task that has transitioned all the way to 'landed' must report
    exactly 'landed' — never a softer or stale status.

    This is the core invariant: Aetheria cannot truthfully say a task is
    done until task_status returns 'landed'.
    """
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)

    task_id = _dispatch(store, objective="Implement feature Y")

    # Walk through the full lifecycle
    store.set_status(task_id, "executing")
    store.set_result(task_id, diff="the diff", test_output="all pass", summary="Feature Y done")
    store.set_status(task_id, "in_review")
    store.set_review(task_id, review_feedback="Approved — ship it")
    store.set_status(task_id, "landed")

    result = tool.handler({"task_id": task_id})
    assert result["status"] == "landed", (
        f"Expected 'landed' but got {result['status']!r} — "
        "task_status is reporting a stale or softened status"
    )


def test_honesty_invariant_landed_task_not_in_open_list(store):
    """Once landed, the task must disappear from the open-task list."""
    from soveryn.platform.delegation.tools import build_task_status_tool
    tool = build_task_status_tool(store=store)

    task_id = _dispatch(store, objective="Feature Z")
    store.set_status(task_id, "executing")
    store.set_result(task_id, diff="d", test_output="ok", summary="s")
    store.set_status(task_id, "in_review")
    store.set_status(task_id, "landed")

    result = tool.handler({})
    ids = [item["id"] for item in result]
    assert task_id not in ids, (
        "A landed task appeared in the open-task list — Aetheria would see it as still open"
    )


# ---------------------------------------------------------------------------
# 6. register_delegation_tools registers BOTH dispatch_task and task_status
# ---------------------------------------------------------------------------

def test_register_delegation_tools_registers_both(store, registry):
    from soveryn.platform.delegation.tools import register_delegation_tools
    register_delegation_tools(registry, store=store)
    names = {spec.name for spec in registry.iter_tools_for_agent("aetheria")}
    assert "dispatch_task" in names
    assert "task_status" in names


# ---------------------------------------------------------------------------
# 7. registry.invoke end-to-end for task_status
# ---------------------------------------------------------------------------

def test_registry_invoke_task_status_with_id(store, registry):
    from soveryn.platform.delegation.tools import register_delegation_tools
    register_delegation_tools(registry, store=store)

    task_id = store.create_task(
        dispatched_by="aetheria",
        objective="Via registry",
        scope="soveryn/x.py",
        acceptance="pytest tests/test_x.py",
    )

    result = registry.invoke("aetheria", "task_status", {"task_id": task_id})
    assert result["id"] == task_id
    assert result["status"] == "dispatched"
    assert result["objective"] == "Via registry"


def test_registry_invoke_task_status_no_args(store, registry):
    from soveryn.platform.delegation.tools import register_delegation_tools
    register_delegation_tools(registry, store=store)

    store.create_task(
        dispatched_by="aetheria",
        objective="Open task",
        scope="soveryn/y.py",
        acceptance="pytest tests/test_y.py",
    )

    result = registry.invoke("aetheria", "task_status", {})
    assert isinstance(result, list)
    assert any(item["objective"] == "Open task" for item in result)


def test_registry_invoke_task_status_not_found(store, registry):
    from soveryn.platform.delegation.tools import register_delegation_tools
    register_delegation_tools(registry, store=store)

    result = registry.invoke("aetheria", "task_status", {"task_id": "no-such-id"})
    assert result["error"] == "not_found"
