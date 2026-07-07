"""TDD tests for soveryn.platform.delegation.tools — dispatch_task tool.

Strict TDD order: tests written first, implementation second.

Run before implementing to confirm RED:
  ~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dispatch_task_tool.py -q
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
# 1. Build function returns a ToolSpec with correct name and owner
# ---------------------------------------------------------------------------

def test_tool_name_and_owner(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    assert tool.name == "dispatch_task"
    assert tool.owner == "aetheria"


def test_tool_owner_kwarg_respected(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store, owner_agent="aetheria")
    assert tool.owner == "aetheria"


# ---------------------------------------------------------------------------
# 2. Schema shape — required fields present, additionalProperties false
# ---------------------------------------------------------------------------

def test_schema_required_fields(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    schema = tool.schema
    assert set(schema.get("required", [])) == {"objective", "scope", "acceptance"}
    assert schema.get("additionalProperties") is False


def test_schema_properties_exist(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    props = tool.schema.get("properties", {})
    for field in ("objective", "scope", "acceptance"):
        assert field in props, f"Missing property: {field}"
        assert props[field].get("type") == "string"


# ---------------------------------------------------------------------------
# 3. Valid call — creates a task and returns {task_id, status:"dispatched"}
# ---------------------------------------------------------------------------

def test_valid_dispatch_returns_task_id_and_status(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    result = tool.handler({
        "objective": "Add docstring to soveryn/x.py",
        "scope": "soveryn/x.py only",
        "acceptance": "pytest tests/test_x.py -q",
    })
    assert "task_id" in result
    assert result["status"] == "dispatched"
    assert isinstance(result["task_id"], str) and result["task_id"]


def test_valid_dispatch_persisted_to_store(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    result = tool.handler({
        "objective": "Fix import in utils.py",
        "scope": "soveryn/utils.py only",
        "acceptance": "pytest tests/test_utils.py",
    })
    task = store.get_task(result["task_id"])
    assert task is not None
    assert task.status == "dispatched"
    assert task.dispatched_by == "aetheria"
    assert task.objective == "Fix import in utils.py"
    assert task.scope == "soveryn/utils.py only"
    assert task.acceptance == "pytest tests/test_utils.py"


def test_valid_dispatch_python_m_acceptance(store):
    """python -m ... is a valid acceptance command prefix."""
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    result = tool.handler({
        "objective": "Implement feature",
        "scope": "soveryn/feature.py",
        "acceptance": "python -m pytest tests/test_feature.py",
    })
    assert result["status"] == "dispatched"


def test_dispatch_dotslash_acceptance_now_rejected(store):
    """'./script' is NO LONGER allowed — acceptance runs as a real subprocess and
    a bare script prefix would execute any (Scotty-written) file in the worktree.
    Only pytest / python -m entrypoints are permitted."""
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    from soveryn.platform.tools.registry import ToolArgError
    tool = build_dispatch_task_tool(store=store)
    with pytest.raises(ToolArgError):
        tool.handler({
            "objective": "Run integration check",
            "scope": "soveryn/integration/",
            "acceptance": "./run_checks.sh",
        })


# ---------------------------------------------------------------------------
# 4. Empty field validation — each required field errors independently
# ---------------------------------------------------------------------------

def test_empty_objective_raises(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    with pytest.raises(ToolArgError):
        tool.handler({
            "objective": "",
            "scope": "soveryn/x.py",
            "acceptance": "pytest tests/test_x.py",
        })


def test_whitespace_objective_raises(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    with pytest.raises(ToolArgError):
        tool.handler({
            "objective": "   ",
            "scope": "soveryn/x.py",
            "acceptance": "pytest tests/test_x.py",
        })


def test_empty_scope_raises(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    with pytest.raises(ToolArgError):
        tool.handler({
            "objective": "Do something",
            "scope": "",
            "acceptance": "pytest tests/test_x.py",
        })


def test_empty_acceptance_raises(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    with pytest.raises(ToolArgError):
        tool.handler({
            "objective": "Do something",
            "scope": "soveryn/x.py",
            "acceptance": "",
        })


# ---------------------------------------------------------------------------
# 5. Acceptance validation — must start with pytest / python -m / ./
# ---------------------------------------------------------------------------

def test_acceptance_not_a_test_command_raises(store):
    """Random prose should not be accepted."""
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    with pytest.raises(ToolArgError):
        tool.handler({
            "objective": "Do something",
            "scope": "soveryn/x.py",
            "acceptance": "looks good",
        })


def test_acceptance_dangerous_command_raises(store):
    """rm -rf / should not be accepted as an acceptance criterion."""
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    with pytest.raises(ToolArgError):
        tool.handler({
            "objective": "Do something",
            "scope": "soveryn/x.py",
            "acceptance": "rm -rf /",
        })


def test_acceptance_bare_filename_raises(store):
    """A bare filename (no ./ prefix) should not pass."""
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    with pytest.raises(ToolArgError):
        tool.handler({
            "objective": "Do something",
            "scope": "soveryn/x.py",
            "acceptance": "run_checks.sh",
        })


def test_acceptance_pytest_passes(store):
    """pytest ... is a valid acceptance command."""
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    result = tool.handler({
        "objective": "Add type hints",
        "scope": "soveryn/x.py",
        "acceptance": "pytest tests/test_x.py -v --tb=short",
    })
    assert result["status"] == "dispatched"


# ---------------------------------------------------------------------------
# 6. register_delegation_tools + end-to-end registry.invoke
# ---------------------------------------------------------------------------

def test_register_delegation_tools(store, registry):
    from soveryn.platform.delegation.tools import register_delegation_tools
    register_delegation_tools(registry, store=store)
    names = {spec.name for spec in registry.iter_tools_for_agent("aetheria")}
    assert "dispatch_task" in names


def test_registry_invoke_end_to_end(store, registry):
    from soveryn.platform.delegation.tools import register_delegation_tools
    register_delegation_tools(registry, store=store)

    result = registry.invoke("aetheria", "dispatch_task", {
        "objective": "Implement logging in daemon.py",
        "scope": "soveryn/daemon.py only, no other files",
        "acceptance": "pytest tests/test_daemon.py -q",
    })
    assert result["status"] == "dispatched"
    task_id = result["task_id"]

    task = store.get_task(task_id)
    assert task is not None
    assert task.dispatched_by == "aetheria"
    assert task.objective == "Implement logging in daemon.py"


def test_registry_invoke_bad_acceptance_raises(store, registry):
    """Registry invoke should surface ToolArgError for bad acceptance criterion."""
    from soveryn.platform.delegation.tools import register_delegation_tools
    register_delegation_tools(registry, store=store)

    with pytest.raises(ToolArgError):
        registry.invoke("aetheria", "dispatch_task", {
            "objective": "Do something",
            "scope": "soveryn/x.py",
            "acceptance": "echo done",
        })


# ---------------------------------------------------------------------------
# 7. Description contract — honest contract text present
# ---------------------------------------------------------------------------

def test_description_mentions_scotty_and_worktree(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    desc = tool.description.lower()
    assert "scotty" in desc
    assert "worktree" in desc


def test_description_mentions_review_approval(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    desc = tool.description.lower()
    # Must convey "nothing goes live until approved" — check for key terms
    assert "review" in desc or "approved" in desc or "jon" in desc


def test_description_warns_not_done_until_landed(store):
    from soveryn.platform.delegation.tools import build_dispatch_task_tool
    tool = build_dispatch_task_tool(store=store)
    desc = tool.description.lower()
    assert "landed" in desc
