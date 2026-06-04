"""Tests for the Vett patrol stack — trigger gates, prompt shape,
source list loader, patrol tools, daemon dry-run + spin-bug resistance.

Patterns mirror the heartbeat tests so anyone reading both files
recognizes the daemon shape.
"""

from __future__ import annotations

import sqlite3
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from soveryn.agents.vett.patrol import (
    LatticeTagSnapshot,
    PatrolBriefingInputs,
    PatrolConfig,
    PatrolSkipReason,
    PatrolSource,
    PatrolSourceError,
    SourceState,
    build_patrol_brief,
    evaluate_tick,
    load_source_list,
    mark_source_error,
    mark_source_visited,
    read_patrol_state,
)
from soveryn.agents.vett.patrol.daemon import PatrolDaemon, PATROL_SESSION_TITLE
from soveryn.agents.vett.tools.patrol_sources import (
    build_mark_source_visited_tool,
    build_read_patrol_sources_tool,
)
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.tools.registry import ToolArgError


# ─── source_list: YAML loader ───────────────────────────────────────────────

def _write_sources_yaml(path: Path, sources: list[dict]) -> Path:
    path.write_text(yaml.safe_dump(sources), encoding="utf-8")
    return path


def test_load_source_list_parses_valid_yaml(tmp_path):
    yaml_path = _write_sources_yaml(tmp_path / "s.yaml", [
        {"url": "https://a.example/", "kind": "html", "domain": "x",
         "visit_every_hours": 6, "keywords": ["alpha"]},
        {"url": "https://b.example/", "kind": "rss", "domain": "y",
         "visit_every_hours": 12},
    ])
    sl = load_source_list(yaml_path)
    assert len(sl) == 2
    assert sl.sources[0].url == "https://a.example/"
    assert sl.sources[0].keywords == ("alpha",)
    assert sl.sources[1].keywords == ()


def test_load_source_list_rejects_missing_file(tmp_path):
    with pytest.raises(PatrolSourceError, match="not found"):
        load_source_list(tmp_path / "missing.yaml")


def test_load_source_list_rejects_non_list_root(tmp_path):
    yaml_path = tmp_path / "s.yaml"
    yaml_path.write_text("not a list\n", encoding="utf-8")
    with pytest.raises(PatrolSourceError, match="list of sources"):
        load_source_list(yaml_path)


def test_load_source_list_rejects_non_http_url(tmp_path):
    yaml_path = _write_sources_yaml(tmp_path / "s.yaml", [
        {"url": "file:///etc/passwd", "kind": "html", "domain": "x",
         "visit_every_hours": 6},
    ])
    with pytest.raises(PatrolSourceError, match="http"):
        load_source_list(yaml_path)


def test_load_source_list_rejects_bad_kind(tmp_path):
    yaml_path = _write_sources_yaml(tmp_path / "s.yaml", [
        {"url": "https://a/", "kind": "scraper", "domain": "x",
         "visit_every_hours": 6},
    ])
    with pytest.raises(PatrolSourceError, match="kind"):
        load_source_list(yaml_path)


def test_load_source_list_rejects_duplicate_urls(tmp_path):
    yaml_path = _write_sources_yaml(tmp_path / "s.yaml", [
        {"url": "https://a/", "kind": "html", "domain": "x", "visit_every_hours": 6},
        {"url": "https://a/", "kind": "rss", "domain": "y", "visit_every_hours": 12},
    ])
    with pytest.raises(PatrolSourceError, match="duplicate"):
        load_source_list(yaml_path)


def test_load_source_list_rejects_unknown_fields(tmp_path):
    yaml_path = _write_sources_yaml(tmp_path / "s.yaml", [
        {"url": "https://a/", "kind": "html", "domain": "x",
         "visit_every_hours": 6, "secret": "shh"},
    ])
    with pytest.raises(PatrolSourceError, match="unknown fields"):
        load_source_list(yaml_path)


def test_load_source_list_handles_empty_file(tmp_path):
    yaml_path = tmp_path / "s.yaml"
    yaml_path.write_text("", encoding="utf-8")
    sl = load_source_list(yaml_path)
    assert len(sl) == 0


# ─── source_list: state read/write ──────────────────────────────────────────

@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    return db


def test_mark_source_visited_inserts_then_updates(lattice_db):
    url = "https://a.example/"
    t1 = datetime(2026, 6, 4, 10, 0, 0)
    t2 = datetime(2026, 6, 4, 16, 0, 0)
    mark_source_visited(lattice_db, url, when=t1)
    state = read_patrol_state(lattice_db, [url])[url]
    assert state.last_visited_at == t1
    assert state.visit_count == 1
    assert state.last_error is None
    mark_source_visited(lattice_db, url, when=t2)
    state2 = read_patrol_state(lattice_db, [url])[url]
    assert state2.last_visited_at == t2
    assert state2.visit_count == 2


def test_mark_source_visited_clears_prior_error(lattice_db):
    url = "https://a.example/"
    mark_source_error(lattice_db, url, "timeout", when=datetime(2026, 6, 4, 9, 0))
    state = read_patrol_state(lattice_db, [url])[url]
    assert state.last_error == "timeout"
    mark_source_visited(lattice_db, url, when=datetime(2026, 6, 4, 10, 0))
    state2 = read_patrol_state(lattice_db, [url])[url]
    assert state2.last_error is None
    assert state2.last_error_at is None


def test_read_patrol_state_returns_empty_for_unknown_urls(lattice_db):
    states = read_patrol_state(lattice_db, ["https://never-visited/"])
    s = states["https://never-visited/"]
    assert s.last_visited_at is None
    assert s.visit_count == 0


# ─── trigger: gates compose correctly ───────────────────────────────────────

def _config(**kw) -> PatrolConfig:
    base = dict(
        enabled=True, dry_run=True,
        interval_seconds=21600, backoff_seconds=1800,
        quiet_hours="", vnext_base="http://x", chat_timeout_seconds=360,
    )
    base.update(kw)
    return PatrolConfig(**base)


NOW = datetime(2026, 6, 4, 12, 0, 0)


def test_trigger_disabled_short_circuits_first():
    e = evaluate_tick(_config(enabled=False), now=NOW,
                     last_patrol_at=None, last_vett_activity_at=None, source_count=5)
    assert not e.eligible
    assert e.skip_reason == PatrolSkipReason.DISABLED


def test_trigger_interval_blocks_until_elapsed():
    last = NOW - timedelta(hours=2)  # under 6h default
    e = evaluate_tick(_config(), now=NOW, last_patrol_at=last,
                     last_vett_activity_at=None, source_count=5)
    assert e.skip_reason == PatrolSkipReason.INTERVAL


def test_trigger_backoff_blocks_after_recent_vett_activity():
    last_patrol = NOW - timedelta(hours=7)
    last_vett = NOW - timedelta(minutes=10)
    e = evaluate_tick(_config(), now=NOW, last_patrol_at=last_patrol,
                     last_vett_activity_at=last_vett, source_count=5)
    assert e.skip_reason == PatrolSkipReason.BACKOFF


def test_trigger_quiet_hours_blocks_in_window():
    config = _config(quiet_hours="11:00-13:00")
    e = evaluate_tick(config, now=NOW, last_patrol_at=None,
                     last_vett_activity_at=None, source_count=5)
    assert e.skip_reason == PatrolSkipReason.QUIET_HOURS


def test_trigger_no_sources_fires_when_list_empty():
    e = evaluate_tick(_config(), now=NOW, last_patrol_at=None,
                     last_vett_activity_at=None, source_count=0)
    assert e.skip_reason == PatrolSkipReason.NO_SOURCES


def test_trigger_eligible_when_everything_passes():
    e = evaluate_tick(_config(), now=NOW, last_patrol_at=NOW - timedelta(hours=10),
                     last_vett_activity_at=None, source_count=5)
    assert e.eligible
    assert e.skip_reason is None


def test_trigger_skip_reason_order_disabled_beats_interval():
    config = _config(enabled=False)
    last = NOW - timedelta(minutes=1)  # would also fail interval
    e = evaluate_tick(config, now=NOW, last_patrol_at=last,
                     last_vett_activity_at=None, source_count=5)
    assert e.skip_reason == PatrolSkipReason.DISABLED


# ─── prompt: structural shape ───────────────────────────────────────────────

def test_patrol_brief_includes_first_patrol_framing():
    inputs = PatrolBriefingInputs(
        hours_since_last_patrol=None,
        sources=(),
        lattice=LatticeTagSnapshot(
            tagged_domains=(), new_node_count_recent_window=0,
            recent_window_minutes=240,
        ),
    )
    brief = build_patrol_brief(inputs, now=NOW)
    assert "[PATROL]" in brief
    assert "First patrol since daemon startup" in brief
    assert "nothing actionable from this patrol" in brief


def test_patrol_brief_separates_due_from_not_due():
    s1 = PatrolSource(url="https://due/", kind="html", domain="d1",
                     visit_every_hours=6)
    s2 = PatrolSource(url="https://fresh/", kind="html", domain="d2",
                     visit_every_hours=24)
    state_due = SourceState(source_url=s1.url, last_visited_at=None,
                            last_error_at=None, last_error=None, visit_count=0)
    state_fresh = SourceState(source_url=s2.url,
                              last_visited_at=NOW - timedelta(hours=1),
                              last_error_at=None, last_error=None, visit_count=3)
    inputs = PatrolBriefingInputs(
        hours_since_last_patrol=7.0,
        sources=((s1, state_due), (s2, state_fresh)),
        lattice=LatticeTagSnapshot(
            tagged_domains=("funding_eu",),
            new_node_count_recent_window=4,
            recent_window_minutes=240,
        ),
    )
    brief = build_patrol_brief(inputs, now=NOW)
    assert "2 total / 1 due" in brief
    assert "→ [d1] https://due/" in brief    # due marker
    assert "Not yet due (1)" in brief
    assert "· [d2] https://fresh/" in brief
    assert "Aetheria-tagged domains" in brief
    assert "funding_eu" in brief


def test_patrol_brief_shows_last_error_in_source_line():
    s = PatrolSource(url="https://err/", kind="html", domain="d", visit_every_hours=6)
    state = SourceState(
        source_url=s.url, last_visited_at=None,
        last_error_at=NOW - timedelta(hours=2),
        last_error="connection refused", visit_count=0,
    )
    inputs = PatrolBriefingInputs(
        hours_since_last_patrol=24.0, sources=((s, state),),
        lattice=LatticeTagSnapshot(
            tagged_domains=(), new_node_count_recent_window=0,
            recent_window_minutes=240,
        ),
    )
    brief = build_patrol_brief(inputs, now=NOW)
    assert "[last error: connection refused]" in brief


# ─── patrol tools ───────────────────────────────────────────────────────────

def test_read_patrol_sources_tool_merges_yaml_and_state(tmp_path, lattice_db):
    yaml_path = _write_sources_yaml(tmp_path / "s.yaml", [
        {"url": "https://due/", "kind": "html", "domain": "d1",
         "visit_every_hours": 6},
        {"url": "https://fresh/", "kind": "html", "domain": "d2",
         "visit_every_hours": 24, "keywords": ["alpha"]},
    ])
    mark_source_visited(lattice_db, "https://fresh/", when=datetime.now() - timedelta(hours=2))
    tool = build_read_patrol_sources_tool(
        lattice_db_path=lattice_db, sources_yaml_path=yaml_path,
    )
    result = tool.handler({})
    assert result["source_count"] == 2
    by_url = {s["url"]: s for s in result["sources"]}
    assert by_url["https://due/"]["due_for_visit"] is True
    assert by_url["https://fresh/"]["due_for_visit"] is False
    assert by_url["https://fresh/"]["visit_count"] == 1
    assert by_url["https://fresh/"]["keywords"] == ["alpha"]


def test_read_patrol_sources_tool_handles_invalid_yaml(tmp_path, lattice_db):
    yaml_path = tmp_path / "broken.yaml"
    yaml_path.write_text("not a list", encoding="utf-8")
    tool = build_read_patrol_sources_tool(
        lattice_db_path=lattice_db, sources_yaml_path=yaml_path,
    )
    result = tool.handler({})
    assert result["error"] == "source_list_invalid"
    assert result["sources"] == []


def test_mark_source_visited_tool_writes_state(lattice_db):
    tool = build_mark_source_visited_tool(lattice_db_path=lattice_db)
    url = "https://a.example/"
    result = tool.handler({"url": url})
    assert result["marked"] is True
    state = read_patrol_state(lattice_db, [url])[url]
    assert state.visit_count == 1


def test_mark_source_visited_tool_rejects_non_http(lattice_db):
    tool = build_mark_source_visited_tool(lattice_db_path=lattice_db)
    with pytest.raises(ToolArgError, match="http"):
        tool.handler({"url": "ftp://x/"})


def test_mark_source_visited_tool_rejects_empty_url(lattice_db):
    tool = build_mark_source_visited_tool(lattice_db_path=lattice_db)
    with pytest.raises(ToolArgError):
        tool.handler({"url": "  "})


# ─── daemon: spin-bug resistance (the heartbeat-class bug) ──────────────────

def test_daemon_does_not_spin_on_consecutive_skipped_ticks(tmp_path):
    """Same regression-guard as heartbeat: a backoff-blocked loop must not
    burn CPU by leaving sleep_target stuck in the past. We start the daemon
    with disabled=True (forces DISABLED skip), watch for 1 second, kill, and
    assert tick count stayed bounded."""
    # Provide a real (empty) lattice DB so DB reads don't fail.
    lattice_db = tmp_path / "lattice.db"
    LatticeStore(lattice_db)
    conv_db = tmp_path / "conv.db"
    # Use a YAML file so _safe_source_count doesn't bomb.
    yaml_path = _write_sources_yaml(tmp_path / "s.yaml", [
        {"url": "https://a/", "kind": "html", "domain": "x", "visit_every_hours": 6},
    ])
    config = PatrolConfig(
        enabled=False,                  # forces DISABLED every tick
        dry_run=True,
        interval_seconds=2,              # tight loop so we accumulate ticks
        backoff_seconds=1800,
        quiet_hours="",
        vnext_base="http://x",
        chat_timeout_seconds=10,
    )
    daemon = PatrolDaemon(
        config, lattice_db=lattice_db, conv_db=conv_db,
        sources_yaml_path=yaml_path,
    )
    t = threading.Thread(target=daemon.run, daemon=True)
    t.start()
    time.sleep(1.0)
    daemon._stop = True
    t.join(timeout=5)
    # Without the bug fix, this loop emits hundreds-of-rows-per-second of
    # DISABLED-skip rows. With the fix (last_tick_at advances every tick),
    # we should see a handful at most over 1s with interval=2s.
    with sqlite3.connect(str(lattice_db)) as con:
        row_count = con.execute(
            "SELECT COUNT(*) FROM vett_patrol_log"
        ).fetchone()[0]
    assert row_count <= 5, (
        f"daemon emitted {row_count} log rows in ~1s — looks like the "
        f"spin bug regressed. Should be <=5 with interval_seconds=2."
    )
