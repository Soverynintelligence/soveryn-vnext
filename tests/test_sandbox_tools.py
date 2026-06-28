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


def test_reflect_and_lessons_tools_registered_for_aetheria_only(tmp_path: Path) -> None:
    registry = ToolRegistry(audit_hook=None)
    register_sandbox_tools(registry, sandbox_root=tmp_path / "sandbox")
    aetheria = {s.name for s in registry.iter_tools_for_agent("aetheria")}
    vett = {s.name for s in registry.iter_tools_for_agent("vett")}
    assert {"sandbox_reflect", "sandbox_get_lessons"} <= aetheria
    assert "sandbox_reflect" not in vett
    assert "sandbox_get_lessons" not in vett


def test_reflect_tool_flow(tmp_path: Path) -> None:
    registry = ToolRegistry(audit_hook=None)
    register_sandbox_tools(registry, sandbox_root=tmp_path / "sandbox")
    # unlock_botany_wing triggers sector_unlock → pending_reflection
    # Default resources: power=50, hull=70 — requirements (power=15, hull=25) are met
    registry.invoke("aetheria", "sandbox_execute_action", {"action_id": "unlock_botany_wing"})
    out = registry.invoke(
        "aetheria",
        "sandbox_reflect",
        {"reason": "r", "regret": "g", "lesson": "expansion is expensive"},
    )
    assert out["recorded"]["lesson"] == "expansion is expensive"
    # engine.get_lessons returns list[dict] — each dict has cycle/trigger/reason/regret/lesson
    lessons = registry.invoke("aetheria", "sandbox_get_lessons", {})
    assert lessons[-1]["lesson"] == "expansion is expensive"


def test_reflect_tool_rejects_empty_fields(tmp_path: Path) -> None:
    registry = ToolRegistry(audit_hook=None)
    register_sandbox_tools(registry, sandbox_root=tmp_path / "sandbox")
    # Trigger a pending reflection first
    registry.invoke("aetheria", "sandbox_execute_action", {"action_id": "unlock_botany_wing"})
    with pytest.raises(ToolArgError):
        registry.invoke("aetheria", "sandbox_reflect", {"reason": "", "regret": "g", "lesson": "l"})


def test_reflect_tool_raises_when_no_reflection_pending(tmp_path: Path) -> None:
    registry = ToolRegistry(audit_hook=None)
    register_sandbox_tools(registry, sandbox_root=tmp_path / "sandbox")
    # No action executed → no pending reflection
    with pytest.raises(ToolArgError, match="no reflection pending"):
        registry.invoke("aetheria", "sandbox_reflect", {"reason": "r", "regret": "g", "lesson": "l"})


def test_get_lessons_returns_empty_list_initially(tmp_path: Path) -> None:
    registry = ToolRegistry(audit_hook=None)
    register_sandbox_tools(registry, sandbox_root=tmp_path / "sandbox")
    lessons = registry.invoke("aetheria", "sandbox_get_lessons", {})
    assert lessons == []
