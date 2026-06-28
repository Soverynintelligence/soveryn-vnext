from pathlib import Path

import pytest

from soveryn.platform.sandbox.tools import register_sandbox_tools
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


def test_sandbox_tools_register_for_aetheria_only(tmp_path: Path) -> None:
    registry = ToolRegistry(audit_hook=None)

    register_sandbox_tools(registry, sandbox_root=tmp_path / "sandbox")

    aetheria_tools = {spec.name for spec in registry.iter_tools_for_agent("aetheria")}
    vett_tools = {spec.name for spec in registry.iter_tools_for_agent("vett")}
    assert {
        "sandbox_get_status",
        "sandbox_list_actions",
        "sandbox_execute_action",
        "sandbox_research",
    } <= aetheria_tools
    assert "sandbox_get_status" not in vett_tools


def test_sandbox_tool_flow_persists_state_and_surfaces_delta(tmp_path: Path) -> None:
    registry = ToolRegistry(audit_hook=None)
    register_sandbox_tools(registry, sandbox_root=tmp_path / "sandbox")

    status = registry.invoke("aetheria", "sandbox_get_status", {})
    result = registry.invoke(
        "aetheria",
        "sandbox_execute_action",
        {"action_id": "patch_hull_with_materials"},
    )

    assert status["resources"]["power"] == 50
    assert result["delta"]["hull"] == 9
    assert result["newly_discovered_rules"][0]["action"] == "patch_hull_with_materials"
    state_path = tmp_path / "sandbox" / "runs" / result["run_id"] / "state.json"
    assert state_path.exists()


def test_sandbox_execute_rejects_unknown_action(tmp_path: Path) -> None:
    registry = ToolRegistry(audit_hook=None)
    register_sandbox_tools(registry, sandbox_root=tmp_path / "sandbox")

    with pytest.raises(ToolArgError, match="not available"):
        registry.invoke("aetheria", "sandbox_execute_action", {"action_id": "guess_random_button"})
