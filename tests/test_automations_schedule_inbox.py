"""Automations schedule due-detection + CC inbox store."""

from __future__ import annotations

from datetime import datetime, timedelta

from soveryn.automations.inbox import append_inbox, list_inbox
from soveryn.automations.schedule import (
    is_due,
    load_state,
    record_fire,
)


def test_is_due_after_last_fire():
    now = datetime(2026, 8, 20, 8, 5, 0)
    last = datetime(2026, 8, 20, 7, 0, 0)
    # daily at 08:00
    assert is_due("0 8 * * *", now=now, last_fired_at=last) is True
    assert is_due("0 8 * * *", now=now, last_fired_at=datetime(2026, 8, 20, 8, 0, 0)) is False


def test_is_due_no_last_fire_only_within_grace():
    # 08:00 cron: at 08:01 → due; at 10:00 → not (would storm all jobs)
    assert is_due("0 8 * * *", now=datetime(2026, 8, 20, 8, 1, 0), last_fired_at=None) is True
    assert is_due("0 8 * * *", now=datetime(2026, 8, 20, 10, 0, 0), last_fired_at=None) is False


def test_record_fire_failure_streak(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    record_fire("morning_brief", status="error", run_id="r1")
    record_fire("morning_brief", status="error", run_id="r2")
    st = load_state()["morning_brief"]
    assert st["failure_streak"] == 2
    record_fire("morning_brief", status="ok", run_id="r3")
    st = load_state()["morning_brief"]
    assert st["failure_streak"] == 0
    assert st["last_status"] == "ok"


def test_inbox_append_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    append_inbox(
        automation_id="morning_brief",
        title="Morning Brief",
        agent="aetheria",
        channels=["command_center"],
        status="ok",
        content="Top story: markets quiet.",
        source="scheduler",
    )
    rows = list_inbox(limit=10)
    assert len(rows) == 1
    assert rows[0]["automation_id"] == "morning_brief"
    assert rows[0]["content"].startswith("Top story")
    assert rows[0]["source"] == "scheduler"
