"""Tests for ThoughtsLog — append-only JSONL pulse black box."""
import json

import pytest

from soveryn.agents.heartbeat.thoughts_log import ThoughtsLog


def _make_record(n: int) -> dict:
    return {
        "pulse_id": f"pulse-{n}",
        "ts": f"2026-06-22T0{n}:00:00Z",
        "material_signals": [f"signal-{n}"],
        "delta": {"change": n},
        "decision": "SURFACE" if n % 2 == 0 else "NO_OP",
        "rationale": f"reason {n}",
        "surfaced": n % 2 == 0,
    }


# ---------------------------------------------------------------------------
# append two records → last() returns the second (exact dict)
# ---------------------------------------------------------------------------


def test_last_returns_second_record(tmp_path):
    log = ThoughtsLog(tmp_path / "thoughts.jsonl")
    r1 = _make_record(1)
    r2 = _make_record(2)
    log.append(r1)
    log.append(r2)
    assert log.last() == r2


# ---------------------------------------------------------------------------
# last() on a missing file path → None
# ---------------------------------------------------------------------------


def test_last_on_missing_file_returns_none(tmp_path):
    log = ThoughtsLog(tmp_path / "nonexistent" / "thoughts.jsonl")
    assert log.last() is None


# ---------------------------------------------------------------------------
# records round-trip through JSONL (one object per line; line count == append count)
# ---------------------------------------------------------------------------


def test_records_round_trip_jsonl(tmp_path):
    path = tmp_path / "thoughts.jsonl"
    log = ThoughtsLog(path)
    records = [_make_record(i) for i in range(5)]
    for r in records:
        log.append(r)

    lines = [l for l in path.read_text().splitlines() if l.strip()]
    assert len(lines) == len(records)
    for line, expected in zip(lines, records):
        assert json.loads(line) == expected


# ---------------------------------------------------------------------------
# append is additive — first record still present after second append
# ---------------------------------------------------------------------------


def test_append_is_additive(tmp_path):
    path = tmp_path / "thoughts.jsonl"
    log = ThoughtsLog(path)
    r1 = _make_record(1)
    r2 = _make_record(2)
    log.append(r1)
    log.append(r2)

    lines = [l for l in path.read_text().splitlines() if l.strip()]
    assert json.loads(lines[0]) == r1
    assert json.loads(lines[1]) == r2


# ---------------------------------------------------------------------------
# last() tolerates trailing blank line / empty file → None, no crash
# ---------------------------------------------------------------------------


def test_last_tolerates_empty_file(tmp_path):
    path = tmp_path / "thoughts.jsonl"
    path.write_text("")
    log = ThoughtsLog(path)
    assert log.last() is None


def test_last_tolerates_trailing_blank_line(tmp_path):
    path = tmp_path / "thoughts.jsonl"
    r = _make_record(1)
    path.write_text(json.dumps(r) + "\n\n")
    log = ThoughtsLog(path)
    assert log.last() == r
