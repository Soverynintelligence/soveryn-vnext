"""Ares detects readers pointed at channels nobody writes to any more.

2026-07-30: the Comms Bus showed nothing for 18 days. Nothing was broken and no
data was lost — it read a channel that had produced nine rows in two months while
537 real events flowed elsewhere. Jon: "someone was sloppy." The sloppiness was
never going back after delegation shipped its own store.

The wiring contract catches wiring never done. This catches wiring gone stale.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from soveryn.agents.ares.findings import Severity
from soveryn.agents.ares.lanes.observability import (
    CHANNELS,
    collect_stale_readers_live,
    last_activity,
    survey_channels,
)


def _db(tmp_path: Path, name: str, ts: str | None) -> Path:
    p = tmp_path / name
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE t (created_at TEXT)")
    if ts is not None:
        con.execute("INSERT INTO t VALUES (?)", (ts,))
    con.commit(); con.close()
    return p


SQL = "SELECT MAX(created_at) FROM t"
NOW = datetime(2026, 7, 30, 12, 0, 0)


class TestSurvey:

    def test_recent_traffic_is_not_stale(self, tmp_path):
        db = _db(tmp_path, "a.db", (NOW - timedelta(days=1)).isoformat())
        rows = survey_channels(
            channels=({"reader": "r", "db": "k", "sql": SQL},),
            dbs={"k": db}, now=NOW,
        )
        assert rows[0]["stale"] is False
        assert rows[0]["age_days"] == 1.0

    def test_old_traffic_is_stale(self, tmp_path):
        """18 days is what actually happened; the default threshold is 30."""
        db = _db(tmp_path, "a.db", (NOW - timedelta(days=40)).isoformat())
        rows = survey_channels(
            channels=({"reader": "r", "db": "k", "sql": SQL},),
            dbs={"k": db}, now=NOW,
        )
        assert rows[0]["stale"] is True
        assert rows[0]["age_days"] == 40.0

    def test_threshold_is_honoured(self, tmp_path):
        db = _db(tmp_path, "a.db", (NOW - timedelta(days=18)).isoformat())
        ch = ({"reader": "r", "db": "k", "sql": SQL},)
        assert survey_channels(channels=ch, dbs={"k": db}, now=NOW,
                               max_age_days=30)[0]["stale"] is False
        assert survey_channels(channels=ch, dbs={"k": db}, now=NOW,
                               max_age_days=5)[0]["stale"] is True

    def test_empty_is_stale_by_default(self, tmp_path):
        db = _db(tmp_path, "a.db", None)
        rows = survey_channels(channels=({"reader": "r", "db": "k", "sql": SQL},),
                               dbs={"k": db}, now=NOW)
        assert rows[0]["stale"] is True

    def test_allow_empty_channels_are_not_flagged(self, tmp_path):
        """An empty review queue is HEALTHY. Nagging about a healthy condition
        trains you to ignore the tool — how the audit caveat got overridden."""
        db = _db(tmp_path, "a.db", None)
        rows = survey_channels(
            channels=({"reader": "r", "db": "k", "sql": SQL, "allow_empty": True},),
            dbs={"k": db}, now=NOW,
        )
        assert rows[0]["stale"] is False

    def test_missing_database_is_a_finding_not_a_crash(self, tmp_path):
        rows = survey_channels(channels=({"reader": "r", "db": "k", "sql": SQL},),
                               dbs={"k": tmp_path / "nope.db"}, now=NOW)
        assert rows[0]["stale"] is True
        assert "missing" in rows[0]["error"]

    def test_bad_sql_is_a_finding_not_a_crash(self, tmp_path):
        """My own first run had two broken queries. A detector that crashes on
        its own bugs is useless; one that reports them is merely noisy."""
        db = _db(tmp_path, "a.db", NOW.isoformat())
        rows = survey_channels(
            channels=({"reader": "r", "db": "k",
                       "sql": "SELECT MAX(nope) FROM t"},),
            dbs={"k": db}, now=NOW,
        )
        assert rows[0]["stale"] is True and rows[0]["error"]

    def test_naive_and_aware_timestamps_both_work(self, tmp_path):
        """delegation.db writes naive local; the context store writes UTC Z.
        Mixing them raised TypeError the first time this met real data."""
        for ts in ((NOW - timedelta(days=2)).isoformat(),
                   (NOW - timedelta(days=2)).isoformat() + "Z"):
            db = _db(tmp_path, f"d{len(ts)}.db", ts)
            rows = survey_channels(
                channels=({"reader": "r", "db": "k", "sql": SQL},),
                dbs={"k": db}, now=NOW,
            )
            assert rows[0]["age_days"] is not None, ts
            assert rows[0]["stale"] is False, ts


class TestFindings:

    def test_dry_channel_becomes_a_warning(self, tmp_path, monkeypatch):
        db = _db(tmp_path, "a.db", (NOW - timedelta(days=90)).isoformat())
        monkeypatch.setattr(
            "soveryn.agents.ares.lanes.observability.CHANNELS",
            ({"reader": "Test channel", "db": "k", "sql": SQL},))
        monkeypatch.setattr(
            "soveryn.agents.ares.lanes.observability.resolve_dbs",
            lambda: {"k": db})

        found = collect_stale_readers_live(now=NOW)
        assert len(found) == 1
        f = found[0]
        assert f.finding_type == "observability.stale_reader"
        # WARNING, not CRITICAL: router.route_finding sends WARNING to the bus and
        # returns BEFORE signal_sink. A dry channel must not page Jon at 3am.
        assert f.severity is Severity.WARNING
        assert f.key == "Test channel"
        assert f.evidence["age_days"] == 90.0

    def test_key_is_stable_so_findings_dedupe_across_scans(self, tmp_path, monkeypatch):
        db = _db(tmp_path, "a.db", (NOW - timedelta(days=90)).isoformat())
        monkeypatch.setattr(
            "soveryn.agents.ares.lanes.observability.CHANNELS",
            ({"reader": "Test channel", "db": "k", "sql": SQL},))
        monkeypatch.setattr(
            "soveryn.agents.ares.lanes.observability.resolve_dbs",
            lambda: {"k": db})
        assert collect_stale_readers_live(now=NOW)[0].id == \
               collect_stale_readers_live(now=NOW)[0].id

    def test_collector_never_raises(self, monkeypatch):
        """Ares must survive a broken probe."""
        def boom():
            raise RuntimeError("resolve failed")
        monkeypatch.setattr(
            "soveryn.agents.ares.lanes.observability.resolve_dbs", boom)
        assert collect_stale_readers_live() == []


class TestRegistry:

    def test_the_comms_bus_channel_that_started_this_is_registered(self):
        readers = {c["reader"] for c in CHANNELS}
        assert any("legacy direct edges" in r for r in readers), (
            "the channel that went 18 days unnoticed must be watched"
        )

    def test_every_channel_names_a_db_and_a_query(self):
        for c in CHANNELS:
            assert c.get("reader") and c.get("db") and c.get("sql"), c

    def test_lane_is_wired_into_the_ares_daemon(self):
        """A detector nobody runs is not a detector."""
        from soveryn.agents.ares.daemon import _default_collectors
        names = [c.__name__ for c in _default_collectors()]
        assert "collect_stale_readers_live" in names
