"""Tests for SignalLog — voice signal recording for later DPO export."""

from soveryn.agents.presence.signal_log import SignalLog


def test_records_edit_signal(tmp_path):
    """Verify record() inserts an edit signal and all() returns it as a dict."""
    log = SignalLog(tmp_path / "s.db")
    log.record("d1", "edit", "orig text", "edited text", "")
    rows = log.all()
    assert len(rows) == 1
    assert rows[0]["action"] == "edit"
    assert rows[0]["final_text"] == "edited text"
    assert rows[0]["draft_id"] == "d1"


def test_records_multiple_signals(tmp_path):
    """Verify multiple records are stored and retrieved."""
    log = SignalLog(tmp_path / "s.db")
    log.record("d1", "approve", "text1", "text1", "looks good")
    log.record("d2", "reject", "text2", "text2", "spam")
    log.record("d3", "edit", "text3", "edited3", "improved tone")

    rows = log.all()
    assert len(rows) == 3
    assert rows[0]["action"] == "approve"
    assert rows[1]["action"] == "reject"
    assert rows[2]["action"] == "edit"


def test_signal_has_created_at(tmp_path):
    """Verify created_at timestamp is populated."""
    log = SignalLog(tmp_path / "s.db")
    log.record("d1", "approve", "text", "text", "reason")
    rows = log.all()
    assert "created_at" in rows[0]
    assert rows[0]["created_at"] is not None


def test_all_returns_empty_list_initially(tmp_path):
    """Verify all() returns empty list when no records exist."""
    log = SignalLog(tmp_path / "s.db")
    rows = log.all()
    assert rows == []
