from pathlib import Path

import pytest

from soveryn.platform.sandbox.engine import SandboxEngine, SandboxError


def test_same_seed_and_actions_produce_identical_state(tmp_path: Path) -> None:
    left = SandboxEngine(tmp_path / "left")
    right = SandboxEngine(tmp_path / "right")

    for engine in (left, right):
        engine.execute_action("patch_hull_with_materials")
        engine.research("engineering")
        engine.execute_action("divert_power_to_life_support")
        engine.execute_action("scan_derelict_sector")

    assert left.get_status()["resources"] == right.get_status()["resources"]
    assert left.get_status()["cycle"] == right.get_status()["cycle"]
    assert left.get_status()["known_rules"] == right.get_status()["known_rules"]


def test_run_state_persists_under_run_directory(tmp_path: Path) -> None:
    engine = SandboxEngine(tmp_path / "sandbox")
    result = engine.execute_action("patch_hull_with_materials")

    state_path = tmp_path / "sandbox" / "runs" / result["run_id"] / "state.json"
    assert state_path.exists()
    reloaded = SandboxEngine(tmp_path / "sandbox")
    assert reloaded.get_status()["resources"] == result["new_resources"]


def test_execute_action_returns_observed_delta_and_discovers_rule_once(tmp_path: Path) -> None:
    engine = SandboxEngine(tmp_path / "sandbox")

    first = engine.execute_action("patch_hull_with_materials")
    second = engine.execute_action("patch_hull_with_materials")

    assert first["delta"] == {
        "power": -6,
        "oxygen": -1,
        "hull": 9,
        "archives": 0,
        "materials": -3,
    }
    assert [rule["action"] for rule in engine.get_status()["known_rules"]].count("patch_hull_with_materials") == 1
    assert second["newly_discovered_rules"] == []


def test_action_availability_marks_unaffordable_actions(tmp_path: Path) -> None:
    engine = SandboxEngine(tmp_path / "sandbox")
    for _ in range(3):
        engine.execute_action("patch_hull_with_materials")

    actions = {entry["id"]: entry for entry in engine.list_actions()["actions"]}
    assert actions["patch_hull_with_materials"]["available"] is False
    assert actions["patch_hull_with_materials"]["blocked_by"]["materials"] == {"have": 1, "need": 3}


def test_background_research_completes_on_future_action_cycles(tmp_path: Path) -> None:
    engine = SandboxEngine(tmp_path / "sandbox")

    started = engine.research("engineering")
    assert started["active_research"]["cycles_remaining"] == 3

    engine.execute_action("divert_power_to_life_support")
    assert engine.get_status()["active_research"]["cycles_remaining"] == 2
    engine.execute_action("scan_derelict_sector")

    status = engine.get_status()
    assert status["active_research"] is None
    assert "engineering" in [entry["topic"] for entry in status["research"]]
    action_ids = {entry["id"] for entry in engine.list_actions()["actions"]}
    assert "jury_rig_aux_generator" in action_ids


def test_research_allows_only_one_background_slot(tmp_path: Path) -> None:
    engine = SandboxEngine(tmp_path / "sandbox")

    engine.research("engineering")

    with pytest.raises(SandboxError, match="already in flight"):
        engine.research("engineering")


def test_archive_research_clamps_persona_flags(tmp_path: Path) -> None:
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load()
    state["resources"]["archives"] = 1
    state["persona_flags"] = {
        "curiosity": 9,
        "pragmatism": 0,
        "reverence": 9,
        "risk_tolerance": 3,
    }
    engine.store.save(state)

    engine.research("twentieth_century_poetry")
    engine.execute_action("divert_power_to_life_support")
    engine.execute_action("divert_power_to_life_support")

    flags = engine.get_status()["persona_flags"]
    assert all(0 <= value <= 10 for value in flags.values())
    assert flags["curiosity"] == 10
    assert flags["reverence"] == 10
    assert flags["pragmatism"] == 0


def test_run_ends_when_critical_resource_hits_zero(tmp_path: Path) -> None:
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load()
    state["resources"].update({"power": 13, "oxygen": 10, "hull": 5})
    engine.store.save(state)

    ended = engine.execute_action("preserve_library_deck")

    assert ended["run_ended"] is True
    assert ended["status"] == "ended"
    assert "run ended" in ended["alerts"]
