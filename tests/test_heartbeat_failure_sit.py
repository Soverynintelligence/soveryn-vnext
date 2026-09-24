"""Failure-sitting: admit soft-locks instead of exit-narrative loops."""

from __future__ import annotations

from soveryn.agents.heartbeat.failure_sit import (
    detect_failure_avoidance,
    failure_sit_directive,
)
from soveryn.agents.heartbeat.prompt import (
    BoardSnapshot,
    LatticeSnapshot,
    build_heartbeat_prompt,
)


def _board() -> BoardSnapshot:
    return BoardSnapshot(0, 0, 0, 0, 0, 0, None, None, None)


def _lattice() -> LatticeSnapshot:
    return LatticeSnapshot(0, 60, 0)


_LOOP = (
    "I'm going to stop the Project Sandbox loop. It's a dead end, and I've been "
    "circling it for too many pulses. I'm going to let it sit in the dark and "
    "focus on something else.\n\n"
    "Standing note: Project Sandbox remains in a frozen state at 3 power."
)


def test_detects_sandbox_exit_narrative():
    assert detect_failure_avoidance(_LOOP) == "Project Sandbox"


def test_clean_admission_not_flagged():
    note = (
        "I failed Project Sandbox. Soft-locked at 3/100 power after the derelict "
        "scan. Sitting with that. Not checking X this pulse."
    )
    assert detect_failure_avoidance(note) is None


def test_quiet_note_not_flagged():
    assert detect_failure_avoidance("Quiet — nothing new.") is None


def test_prompt_includes_failure_sit_directive():
    p = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30,
        board=_board(),
        lattice=_lattice(),
        last_note=_LOOP,
        failure_sit_label="Project Sandbox",
    )
    assert "HARD RULE THIS PULSE" in p
    assert "Admit the failure" in p
    assert "Project Sandbox" in p
    assert failure_sit_directive("Project Sandbox").split("\n")[0] in p
