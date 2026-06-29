from datetime import date  # noqa
from pathlib import Path
import pytest
from soveryn.platform.sandbox.engine import SandboxEngine, SandboxError

def test_trigger_sets_pending_and_blocks_further_actions(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    # unlock_botany_wing unlocks a sector → major event → pending_reflection
    state = engine.store.load(); state["resources"].update({"power": 60, "hull": 60}); engine.store.save(state)
    engine.execute_action("unlock_botany_wing")
    assert engine.get_status().get("pending_reflection") is not None
    with pytest.raises(SandboxError, match="reflection required"):
        engine.execute_action("recycle_air_reserves")

def test_research_also_blocked_while_reflection_pending(tmp_path):
    # The forced reflection must be ABSOLUTE — research() can't be used to move
    # past a pending reflection any more than execute_action can.
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load(); state["resources"].update({"power": 60, "hull": 60}); engine.store.save(state)
    engine.execute_action("unlock_botany_wing")  # sector unlock → pending_reflection
    assert engine.get_status().get("pending_reflection") is not None
    with pytest.raises(SandboxError, match="reflection required"):
        engine.research("engineering")

def test_reflect_records_clears_and_backfills(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load(); state["resources"].update({"power": 60, "hull": 60}); engine.store.save(state)
    engine.execute_action("unlock_botany_wing")
    engine.reflect(reason="needed oxygen capacity", regret="spent hull I'll miss", lesson="expansion early costs survival margin")
    status = engine.get_status()
    assert status.get("pending_reflection") is None
    lessons = engine.get_lessons()
    assert lessons and lessons[-1]["lesson"] == "expansion early costs survival margin"

def test_reflect_with_nothing_pending_errors(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    with pytest.raises(SandboxError, match="no reflection pending"):
        engine.reflect(reason="x", regret="y", lesson="z")

def test_run_end_forces_reflection_and_reflect_is_exempt(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load(); state["resources"].update({"power": 13, "oxygen": 10, "hull": 5}); engine.store.save(state)
    engine.execute_action("preserve_library_deck")  # crashes oxygen → run ends
    status = engine.get_status()
    assert status["status"] == "ended"
    assert status["pending_reflection"]["trigger"] == "run_end"
    with pytest.raises(SandboxError, match="run has ended"):
        engine.execute_action("recycle_air_reserves")
    # reflect is the ONE allowed action on an ended run:
    engine.reflect(reason="tried to save the library", regret="lost the station", lesson="don't preserve archives at the edge of collapse")
    assert engine.get_status()["pending_reflection"] is None

def test_provenance_seam_reflection_stays_sandbox_local(tmp_path):
    # The engine must have NO cognition/lattice dependency: reflections live only in sandbox state.
    import soveryn.platform.sandbox.engine as eng
    src = Path(eng.__file__).read_text()
    assert "cognition" not in src and "lattice" not in src.lower()
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load(); state["resources"].update({"power": 60, "hull": 60}); engine.store.save(state)
    engine.execute_action("unlock_botany_wing")
    engine.reflect(reason="a", regret="b", lesson="c")
    state_file = tmp_path / "sandbox" / "runs" / engine.get_status()["run_id"] / "state.json"
    assert "lesson" in state_file.read_text()  # reflection persisted ONLY here
