"""A turn that admits it wrote nothing is not a finished commission."""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.citizens import commissions
from soveryn.citizens.registry import Citizen, connect, register
from soveryn.citizens.runtime import execute_claimed

_TASK = (
    "Lounge echo-loop fix in soveryn/rooms/lounge.py. "
    "Land both guards in notify_lounge and run pytest."
)


def _seed(db: Path, work: Path) -> None:
    desk = work / "forge"
    desk.mkdir(parents=True)
    (work / "aetheria").mkdir()
    with connect(db) as conn:
        register(conn, Citizen(id="forge", display_name="Forge", workspace_path=str(desk)))
        register(conn, Citizen(id="aetheria", display_name="Aetheria", workspace_path=str(work / "aetheria")))


def _claim(db: Path, body: str) -> dict:
    with connect(db) as conn:
        commissions.enqueue(conn, "forge", body, at="2026-09-30T12:00:00Z")
        claimed = commissions.claim(conn, "forge", worker="test", at="2026-09-30T12:00:01Z")
    assert claimed is not None
    return claimed


def test_not_complete_fails_and_does_not_brief(tmp_path: Path):
    db = tmp_path / "c.db"
    _seed(db, tmp_path / "desks")
    claimed = _claim(db, _TASK)

    execute_claimed(
        db,
        claimed,
        process_fn=lambda *_: (
            "NOT COMPLETE. No writes landed. Budget died in reads. Zero bytes written."
        ),
        at="2026-09-30T12:00:02Z",
    )

    with connect(db) as conn:
        rows = conn.execute(
            "SELECT citizen_id, state, error FROM commissions ORDER BY created_at"
        ).fetchall()
    assert [(r["citizen_id"], r["state"]) for r in rows] == [("forge", "failed")]
    assert "without a write" in (rows[0]["error"] or "")


def test_a_real_result_still_closes_done(tmp_path: Path):
    db = tmp_path / "c.db"
    _seed(db, tmp_path / "desks")
    claimed = _claim(db, _TASK)

    execute_claimed(
        db,
        claimed,
        process_fn=lambda *_: "Landed the guard in notify_lounge. pytest: 12 passed.",
        at="2026-09-30T12:00:02Z",
    )

    with connect(db) as conn:
        row = commissions.get(conn, claimed["id"])
    assert row is not None
    assert row["state"] == "done"


def test_third_attempt_at_the_same_unwritten_task_is_refused(tmp_path: Path):
    db = tmp_path / "c.db"
    _seed(db, tmp_path / "desks")
    for n in range(2):
        claimed = _claim(db, _TASK + f" Attempt notes {n}.")
        execute_claimed(
            db,
            claimed,
            process_fn=lambda *_: "NOT COMPLETE\nNo file was written.",
            at=f"2026-09-30T12:0{n}:02Z",
        )

    with connect(db) as conn:
        with pytest.raises(ValueError, match="not queued again"):
            commissions.enqueue(conn, "forge", _TASK + " Attempt notes 2.", at="2026-09-30T12:03:00Z")


def test_lounge_nudges_can_still_repeat(tmp_path: Path):
    db = tmp_path / "c.db"
    _seed(db, tmp_path / "desks")
    body = "Lounge nudge: eve is in the room — 3 unread note(s) on the wall. (auto-nudge)"
    with connect(db) as conn:
        for n in range(2):
            commissions.enqueue(conn, "forge", body, at=f"2026-09-30T11:0{n}:00Z")
            claimed = commissions.claim(conn, "forge", worker="test", at=f"2026-09-30T11:0{n}:01Z")
            assert claimed is not None
            commissions.fail(
                conn, claimed["id"], error=commissions.INCOMPLETE_ERROR,
                at=f"2026-09-30T11:0{n}:02Z",
            )
        third = commissions.enqueue(conn, "forge", body, at="2026-09-30T11:02:00Z")
    assert third
