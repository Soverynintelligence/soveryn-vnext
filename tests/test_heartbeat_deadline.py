"""Task 5: Deadline lane — regex date bridge + structured deadline_date read.

Tests for:
1. extract_dates(text, now) — pure parser (no DB, no time imports)
2. _build_dated_items(rows, now) — regex bridge over coordination nodes
3. End-to-end: _gather_material_signals produces deadline MaterialSignal
   when a coordination node text mentions a near date.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

# ── Pure parser tests ────────────────────────────────────────────────────────

from soveryn.agents.heartbeat.date_extract import extract_dates


NOW_DATE = date(2026, 6, 29)
NOW_DT = datetime(2026, 6, 29, 12, 0, 0)


class TestExtractDates:
    def test_month_day_verbal_upcoming(self):
        """'June 30' should parse to 2026-06-30 (1 day away, upcoming)."""
        results = extract_dates("due June 30 for filing", NOW_DATE)
        assert date(2026, 6, 30) in results

    def test_month_abbrev_upcoming(self):
        """'Jun 30' short form should also be parsed."""
        results = extract_dates("deadline Jun 30", NOW_DATE)
        assert date(2026, 6, 30) in results

    def test_month_day_with_explicit_year(self):
        """'June 30 2026' or 'June 30, 2026' should respect the year."""
        results = extract_dates("submit by June 30, 2026", NOW_DATE)
        assert date(2026, 6, 30) in results

    def test_iso_date_parsed(self):
        """'2026-06-30' ISO format should be recognized."""
        results = extract_dates("target date 2026-06-30", NOW_DATE)
        assert date(2026, 6, 30) in results

    def test_us_slash_md(self):
        """'06/30' M/D slash format should be parsed to current/next year."""
        results = extract_dates("due 06/30", NOW_DATE)
        assert date(2026, 6, 30) in results

    def test_us_slash_mdy_full(self):
        """'6/30/2026' full US M/D/YYYY format should be recognized."""
        results = extract_dates("deadline 6/30/2026", NOW_DATE)
        assert date(2026, 6, 30) in results

    def test_no_date_returns_empty(self):
        """Text with no date should return an empty list."""
        results = extract_dates("meet with team to discuss the plan", NOW_DATE)
        assert results == []

    def test_garbage_not_misparsed(self):
        """'30 of something' and other garbage must not produce spurious dates."""
        results = extract_dates("the 30 of something odd", NOW_DATE)
        # Might return something for "30" but should NOT crash; if it does
        # return dates, they must all be real date objects.
        for d in results:
            assert isinstance(d, date)
        # Specifically: '30 of something' must not be parsed as a date.
        # The number '30' alone without a month name is not a valid date.
        assert date(2026, 6, 30) not in results

    def test_past_month_day_rolls_to_next_year_when_far_past(self):
        """'January 5' when now is June 29 — that date was >7 days ago.
        Roll to next year (2027-01-05) so it reads as upcoming not overdue."""
        results = extract_dates("file by January 5", NOW_DATE)
        # Jan 5 is well past — should give next year
        assert date(2027, 1, 5) in results
        assert date(2026, 1, 5) not in results

    def test_upcoming_same_year_not_rolled(self):
        """'July 15' when now is June 29 is upcoming this year — don't roll."""
        results = extract_dates("deadline July 15", NOW_DATE)
        assert date(2026, 7, 15) in results
        assert date(2027, 7, 15) not in results

    def test_multiple_dates_in_text(self):
        """Text with two dates should return both."""
        results = extract_dates("From 2026-07-01 to 2026-07-30", NOW_DATE)
        assert date(2026, 7, 1) in results
        assert date(2026, 7, 30) in results

    def test_month_day_no_year_in_current_year_far_past_rolls(self):
        """A date >7 days past in current year → rolls to next year."""
        # June 1 is 28 days before June 29
        results = extract_dates("June 1 deadline", NOW_DATE)
        assert date(2027, 6, 1) in results
        assert date(2026, 6, 1) not in results

    # ── Ordinal suffix tests — prove existing behavior, guard against regression ──
    # These document that ordinal suffixes (st/nd/rd/th) already parse correctly.
    # A future maintainer who sees the verbal regex and thinks "it doesn't handle
    # ordinals" should look here first before touching the regex.

    def test_ordinal_th_grant_deadline(self):
        """'June 30th' (th suffix) must parse to date(2026,6,30).
        now=date(2026,6,25) so 30th is 5 days away — not rolled."""
        results = extract_dates("NC grant due June 30th for filing", date(2026, 6, 25))
        assert date(2026, 6, 30) in results

    def test_ordinal_rd_upcoming(self):
        """'June 3rd' (rd suffix) must parse to date(2026,6,3).
        now=date(2026,6,1) so 3rd is 2 days away — not rolled."""
        results = extract_dates("filing by June 3rd", date(2026, 6, 1))
        assert date(2026, 6, 3) in results

    def test_ordinal_st_in_mixed_text(self):
        """'June 21st' (st suffix) must parse to date(2026,6,21).
        'the 21st...' preamble must not confuse the parser.
        now=date(2026,6,15) so 21st is 6 days away — not rolled."""
        results = extract_dates("the 21st... June 21st", date(2026, 6, 15))
        assert date(2026, 6, 21) in results


# ── Regex bridge / _build_dated_items tests ─────────────────────────────────

from soveryn.agents.heartbeat.date_extract import build_dated_items


class TestBuildDatedItems:
    def _make_row(self, node_id, content, provenance=None):
        """Helper: build a fake row dict like sqlite3.Row."""
        return {
            "id": node_id,
            "content": content,
            "provenance": json.dumps(provenance or {}),
        }

    def test_near_date_in_content_produces_item(self):
        """Node content mentioning a date ≤7 days away → dated_item returned."""
        row = self._make_row("node-1", "NC Incentive Grant due June 30")
        items = build_dated_items([row], NOW_DATE)
        assert len(items) >= 1
        assert items[0]["date"] == date(2026, 6, 30)
        assert items[0]["fuzzy"] is True

    def test_far_date_in_content_still_returned(self):
        """build_dated_items returns ALL parsed dates; the ≤7-day gate is in
        detect_materiality, not here."""
        row = self._make_row("node-1", "target July 30")
        items = build_dated_items([row], NOW_DATE)
        assert any(i["date"] == date(2026, 7, 30) for i in items)

    def test_no_date_in_content_produces_no_item(self):
        """Node with no date text → no dated_item."""
        row = self._make_row("node-2", "Discuss with team")
        items = build_dated_items([row], NOW_DATE)
        assert items == []

    def test_structured_deadline_date_takes_precedence(self):
        """If provenance has a 'deadline_date' ISO field, prefer it over regex."""
        prov = {"status": "Open", "deadline_date": "2026-07-05"}
        row = self._make_row("node-3", "NC Grant due June 30", prov)
        items = build_dated_items([row], NOW_DATE)
        # Should have a non-fuzzy item for the structured date
        structured = [i for i in items if not i.get("fuzzy", True)]
        assert len(structured) >= 1
        assert structured[0]["date"] == date(2026, 7, 5)

    def test_structured_deadline_date_is_not_fuzzy(self):
        """Structured deadline_date items carry fuzzy=False."""
        prov = {"deadline_date": "2026-07-10"}
        row = self._make_row("node-4", "whatever text", prov)
        items = build_dated_items([row], NOW_DATE)
        structured = [i for i in items if not i.get("fuzzy", True)]
        assert len(structured) == 1
        assert structured[0]["fuzzy"] is False

    def test_ref_is_node_id_or_title(self):
        """ref should be the first line of content (title) or the node id."""
        row = self._make_row("node-5", "Grant application\nBody text here")
        items = build_dated_items([row], NOW_DATE)
        # If dates found, ref should use first-line title or node id
        for item in items:
            assert item["ref"] in ("Grant application", "node-5")

    def test_multiple_nodes_multiple_items(self):
        """Two nodes each with dates → two separate dated items."""
        rows = [
            self._make_row("n1", "due June 30"),
            self._make_row("n2", "file by 2026-07-15"),
        ]
        items = build_dated_items(rows, NOW_DATE)
        dates_found = {i["date"] for i in items}
        assert date(2026, 6, 30) in dates_found
        assert date(2026, 7, 15) in dates_found


# ── End-to-end integration: _gather_material_signals ────────────────────────

from soveryn.agents.heartbeat.daemon import HeartbeatDaemon
from soveryn.agents.heartbeat.trigger import HeartbeatConfig
from soveryn.agents.heartbeat.materiality import MaterialSignal


def _make_test_lattice_db(tmp_path: Path, nodes: list[dict]) -> Path:
    """Create a minimal lattice DB with the nodes table + heartbeat_log."""
    db_path = tmp_path / "lattice_vnext.db"
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "CREATE TABLE nodes ("
            "id TEXT PRIMARY KEY, type TEXT, content TEXT, "
            "created_at TEXT, updated_at TEXT, provenance TEXT)"
        )
        con.execute(
            "CREATE TABLE heartbeat_log ("
            "id TEXT PRIMARY KEY, triggered_at TEXT, completed_at TEXT, "
            "eligible INTEGER, skip_reason TEXT, action_taken INTEGER, "
            "tool_call_count INTEGER, response_length INTEGER, error TEXT, "
            "dry_run INTEGER DEFAULT 0, surfaced_to_chat INTEGER DEFAULT 0)"
        )
        for n in nodes:
            con.execute(
                "INSERT INTO nodes VALUES (?,?,?,?,?,?)",
                (
                    n["id"], n.get("type", "coordination"),
                    n.get("content", ""),
                    n.get("created_at", NOW_DT.isoformat()),
                    n.get("updated_at", NOW_DT.isoformat()),
                    json.dumps(n.get("provenance", {})),
                ),
            )
    return db_path


def _make_test_conv_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "conv.db"
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "CREATE TABLE conversation_meta "
            "(session_id TEXT PRIMARY KEY, agent TEXT, title TEXT, updated_at TEXT)"
        )
    return db_path


def _make_test_salience_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "salience.db"
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS salience_candidates "
            "(id TEXT, flagged_at TEXT, status TEXT)"
        )
    return db_path


def _make_daemon(tmp_path: Path, nodes: list[dict]) -> HeartbeatDaemon:
    lattice_db = _make_test_lattice_db(tmp_path, nodes)
    conv_db = _make_test_conv_db(tmp_path)
    salience_db = _make_test_salience_db(tmp_path)
    config = HeartbeatConfig(
        enabled=True,
        interval_seconds=600,
        backoff_seconds=300,
        quiet_hours="",
        dry_run=True,
    )
    return HeartbeatDaemon(
        config,
        lattice_db=lattice_db,
        conv_db=conv_db,
        salience_db=salience_db,
    )


class TestGatherMaterialSignalsDeadlineLane:
    def test_near_date_in_node_content_produces_deadline_signal(self, tmp_path):
        """Open coordination node mentioning a date ≤7 days out → deadline signal."""
        near_date = (NOW_DATE + timedelta(days=3)).strftime("%-m/%-d/%Y")
        node = {
            "id": "coord-near",
            "type": "coordination",
            "content": f"NC Incentive Grant due {near_date}",
            "provenance": {"status": "Open", "board": "Blueprint"},
        }
        daemon = _make_daemon(tmp_path, [node])
        signals = daemon._gather_material_signals(NOW_DT)
        deadline_sigs = [s for s in signals if s.kind == "deadline"]
        assert len(deadline_sigs) >= 1, (
            f"Expected deadline signal for node mentioning date "
            f"'{near_date}' (3 days away), got: {signals}"
        )

    def test_far_date_in_node_does_not_produce_deadline_signal(self, tmp_path):
        """Open node mentioning a date 60 days out → no deadline signal."""
        far_date = (NOW_DATE + timedelta(days=60)).strftime("%-m/%-d/%Y")
        node = {
            "id": "coord-far",
            "type": "coordination",
            "content": f"Long-range goal due {far_date}",
            "provenance": {"status": "Open", "board": "Blueprint"},
        }
        daemon = _make_daemon(tmp_path, [node])
        signals = daemon._gather_material_signals(NOW_DT)
        deadline_sigs = [s for s in signals if s.kind == "deadline"]
        assert deadline_sigs == [], (
            f"Expected no deadline signal for date 60 days out, got: {deadline_sigs}"
        )

    def test_structured_deadline_date_wins_over_regex(self, tmp_path):
        """If provenance has deadline_date, use it; don't use regex-parsed date."""
        # Content mentions June 30 (1 day away) but structured field says July 10
        structured_date = "2026-07-10"  # 11 days away — outside ≤7-day gate
        node = {
            "id": "coord-structured",
            "type": "coordination",
            "content": "NC Grant due June 30",  # 1 day away — would trigger if regex used
            "provenance": {
                "status": "Open",
                "board": "Blueprint",
                "deadline_date": structured_date,  # 11 days away
            },
        }
        daemon = _make_daemon(tmp_path, [node])
        signals = daemon._gather_material_signals(NOW_DT)
        deadline_sigs = [s for s in signals if s.kind == "deadline"]
        # The structured date (July 10, 11 days out) is beyond the 7-day gate.
        # If regex were used, June 30 (1 day away) would trigger.
        # Correct behavior: no deadline signal (structured date wins, and it's >7 days).
        assert deadline_sigs == [], (
            f"Expected structured deadline_date to win over regex (July 10 is >7 days), "
            f"got: {deadline_sigs}"
        )

    def test_non_coordination_node_skipped(self, tmp_path):
        """Only coordination-type nodes are scanned for dates."""
        near_date = (NOW_DATE + timedelta(days=2)).strftime("%-m/%-d/%Y")
        node = {
            "id": "fact-node",
            "type": "fact",  # NOT coordination
            "content": f"Some fact mentioning {near_date}",
            "provenance": {"status": "Open"},
        }
        daemon = _make_daemon(tmp_path, [node])
        signals = daemon._gather_material_signals(NOW_DT)
        deadline_sigs = [s for s in signals if s.kind == "deadline"]
        assert deadline_sigs == [], "Non-coordination nodes should not feed deadline lane"

    def test_archived_node_skipped(self, tmp_path):
        """Archived coordination nodes should not produce deadline signals."""
        near_date = (NOW_DATE + timedelta(days=2)).strftime("%-m/%-d/%Y")
        node = {
            "id": "coord-archived",
            "type": "coordination",
            "content": f"Archived task due {near_date}",
            "provenance": {"status": "Archived", "board": "Blueprint"},
        }
        daemon = _make_daemon(tmp_path, [node])
        signals = daemon._gather_material_signals(NOW_DT)
        deadline_sigs = [s for s in signals if s.kind == "deadline"]
        assert deadline_sigs == [], "Archived nodes should be skipped"

    def test_existing_stall_detection_still_works(self, tmp_path):
        """Existing stall detection must remain green alongside deadline lane."""
        stale_time = (NOW_DT - timedelta(hours=60)).isoformat()
        node = {
            "id": "coord-stall",
            "type": "coordination",
            "content": "Stalled task",
            "updated_at": stale_time,
            "provenance": {"status": "Open", "board": "Blueprint"},
        }
        daemon = _make_daemon(tmp_path, [node])
        signals = daemon._gather_material_signals(NOW_DT)
        stall_sigs = [s for s in signals if s.kind == "stall"]
        assert len(stall_sigs) >= 1, f"Expected stall signal for 60h-old node, got: {signals}"
