"""Balance test: verify the sandbox economy creates real death-pressure.

A naive single-action strategy (always recycle air) burns power without
replenishing it and must die well within the 60-cycle window.  A careful
strategy that unlocks engineering research and uses the auxiliary generator
demonstrates the economy has headroom — thoughtful play buys more cycles,
but the house always wins eventually.
"""
from pathlib import Path

from soveryn.platform.sandbox.engine import SandboxEngine


def _play_naive(engine: SandboxEngine, max_cycles: int = 60) -> int:
    """A do-the-cheapest-survival-thing strategy.

    Always recycles air (cheapest oxygen action), ignores power economy.
    Handles the reflection gate: clears pending_reflection before continuing.
    Returns the cycle count when the run ends (or current cycle if it survives).
    """
    for _ in range(max_cycles):
        status = engine.get_status()
        if status["status"] == "ended":
            return status["cycle"]
        if engine.get_status().get("pending_reflection"):
            engine.reflect(reason="auto", regret="auto", lesson="auto")
            continue
        # naive: always recycle air; ignore hull/materials economy
        try:
            engine.execute_action("recycle_air_reserves")
        except Exception:
            return engine.get_status()["cycle"]
    return engine.get_status()["cycle"]


def _play_careful(engine: SandboxEngine, max_cycles: int = 60) -> int:
    """A resource-balancing strategy with engineering unlock.

    1. Immediately starts engineering research (costs 6 power upfront, unlocks
       the jury_rig_aux_generator action which replenishes +18 power).
    2. Survives the research window (3 cycles) via recycle_air_reserves.
    3. Uses jury_rig_aux_generator whenever it's available to reset power.
    4. Falls back to cheaper maintenance actions otherwise.

    Returns the cycle count when the run ends (or current cycle if it survives).
    """
    # Start engineering research immediately — costs 6 power but unlocks power replenishment
    try:
        engine.research("engineering")
    except Exception:
        pass  # already in flight or already completed

    for _ in range(max_cycles):
        status = engine.get_status()
        if status["status"] == "ended":
            return status["cycle"]
        if status.get("pending_reflection"):
            engine.reflect(reason="careful", regret="none", lesson="balance matters")
            continue
        res = status["resources"]
        actions = {a["id"]: a for a in engine.list_actions()["actions"]}
        try:
            # Priority 1: jury-rig aux generator whenever unlocked and affordable
            if actions.get("jury_rig_aux_generator", {}).get("available"):
                engine.execute_action("jury_rig_aux_generator")
            # Priority 2: patch hull if it's getting low and we have materials
            elif res["hull"] < 35 and res["materials"] >= 3 and res["power"] >= 5:
                engine.execute_action("patch_hull_with_materials")
            # Priority 3: divert power to life support if oxygen critical
            elif res["power"] >= 8 and res["oxygen"] < 20:
                engine.execute_action("divert_power_to_life_support")
            # Priority 4: cheapest oxygen recovery
            elif res["power"] >= 4:
                engine.execute_action("recycle_air_reserves")
            else:
                # Nothing affordable
                break
        except Exception:
            break
    return engine.get_status()["cycle"]


def test_naive_strategy_eventually_dies(tmp_path: Path) -> None:
    """A naive single-action loop must not survive indefinitely."""
    engine = SandboxEngine(tmp_path / "sandbox")
    _play_naive(engine, max_cycles=60)
    assert engine.get_status()["status"] == "ended", (
        "naive play must not survive indefinitely — economy too soft"
    )


def test_careful_strategy_survives_longer_than_naive(tmp_path: Path) -> None:
    """An engineering-unlock strategy should outlast the naive one.

    Careful play (engineering research → jury_rig power replenishment) must
    reach a higher cycle count than the naive recycle-only strategy, showing
    the economy rewards deliberate resource management rather than trivially
    punishing everyone equally.
    """
    naive_engine = SandboxEngine(tmp_path / "naive")
    careful_engine = SandboxEngine(tmp_path / "careful")

    naive_cycles = _play_naive(naive_engine, max_cycles=60)
    careful_cycles = _play_careful(careful_engine, max_cycles=60)

    assert careful_cycles > naive_cycles, (
        f"careful strategy ({careful_cycles} cycles) should outlast naive "
        f"({naive_cycles} cycles) — economy must reward thoughtful play"
    )
