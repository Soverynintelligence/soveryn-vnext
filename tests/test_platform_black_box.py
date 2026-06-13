"""BlackBox + TurnRecorder unit tests — pure module, no AgentLoop.

The integration with AgentLoop is tested separately in
test_agent_loop_black_box.py. This file only exercises the recorder API
and JSONL output shape.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.platform.black_box import BlackBox, TurnRecorder


@pytest.fixture
def bb(tmp_path: Path) -> BlackBox:
    return BlackBox(tmp_path / "bb")


# ─── No-tool turns produce zero disk writes ───────────────────────────────────

def test_finalize_without_actions_writes_nothing(bb: BlackBox, tmp_path: Path):
    """If no record_action was called, finalize is a no-op — nothing on disk."""
    recorder = bb.begin_turn(session_id="s1", agent="aetheria", user_message="hi")
    result = recorder.finalize(final_content="hello back", finish_reason="stop")
    assert result is None
    # Filesystem under the BlackBox root must be empty
    bb_root = tmp_path / "bb"
    if bb_root.exists():
        produced = list(bb_root.rglob("*.jsonl"))
        assert produced == [], f"unexpected JSONL files: {produced}"


# ─── A turn with one tool round produces one JSONL line ──────────────────────

def test_single_round_writes_one_line(bb: BlackBox, tmp_path: Path):
    recorder = bb.begin_turn(session_id="sess-A", agent="aetheria", user_message="find X")
    recorder.record_action(
        round_index=0,
        tool_calls=[{"id": "call_1", "function": {"name": "search", "arguments": '{"q":"X"}'}}],
        content="",
    )
    recorder.record_observation(
        round_index=0,
        results=[{"call_id": "call_1", "name": "search", "content": "found X", "error": None}],
    )
    path = recorder.finalize(final_content="X is here", finish_reason="stop")
    assert path is not None
    assert path.name == "sess-A.jsonl"
    assert path.parent.name == "aetheria"
    content = path.read_text().strip().splitlines()
    assert len(content) == 1
    row = json.loads(content[0])
    assert row["session_id"] == "sess-A"
    assert row["agent"] == "aetheria"
    assert row["user_message"] == "find X"
    assert row["final_content"] == "X is here"
    assert row["finish_reason"] == "stop"
    assert len(row["actions_and_observations"]) == 2
    assert row["actions_and_observations"][0]["type"] == "action"
    assert row["actions_and_observations"][1]["type"] == "observation"


# ─── Telemetry block shape ────────────────────────────────────────────────────

def test_telemetry_block_counts_rounds_and_tool_calls(bb: BlackBox):
    recorder = bb.begin_turn(session_id="t1", agent="aetheria", user_message="...")
    recorder.record_action(
        round_index=0,
        tool_calls=[
            {"id": "c1", "function": {"name": "search", "arguments": "{}"}},
            {"id": "c2", "function": {"name": "search", "arguments": "{}"}},
        ],
        content="",
    )
    recorder.record_observation(round_index=0, results=[
        {"call_id": "c1", "name": "search", "content": "r1", "error": None},
        {"call_id": "c2", "name": "search", "content": "r2", "error": None},
    ])
    recorder.record_action(
        round_index=1,
        tool_calls=[{"id": "c3", "function": {"name": "read_doc", "arguments": "{}"}}],
        content="",
    )
    recorder.record_observation(round_index=1, results=[
        {"call_id": "c3", "name": "read_doc", "content": "r3", "error": None},
    ])
    path = recorder.finalize(final_content="done", finish_reason="stop")
    row = json.loads(path.read_text().strip())
    tele = row["telemetry"]
    assert tele["num_rounds"] == 2
    assert tele["tool_calls"] == {"search": 2, "read_doc": 1}
    assert tele["tool_error_count"] == 0
    assert tele["tool_round_limit_hit"] is False
    assert tele["finish_reason"] == "stop"
    assert isinstance(tele["wall_time_ms"], int)


def test_telemetry_marks_tool_round_limit_explicitly(bb: BlackBox):
    """finish_reason='tool_round_limit' MUST surface as a dedicated flag so
    "broken steering rack" failures (Aetheria's verdict on Harness-1) are
    greppable. This is the load-bearing failure mode per Jon's lock."""
    recorder = bb.begin_turn(session_id="t2", agent="vett", user_message="...")
    recorder.record_action(
        round_index=0,
        tool_calls=[{"id": "c1", "function": {"name": "search", "arguments": "{}"}}],
        content="",
    )
    recorder.record_observation(round_index=0, results=[
        {"call_id": "c1", "name": "search", "content": "empty", "error": None},
    ])
    path = recorder.finalize(final_content="", finish_reason="tool_round_limit")
    row = json.loads(path.read_text().strip())
    assert row["finish_reason"] == "tool_round_limit"
    assert row["telemetry"]["tool_round_limit_hit"] is True
    assert row["telemetry"]["finish_reason"] == "tool_round_limit"


def test_telemetry_counts_tool_errors(bb: BlackBox):
    recorder = bb.begin_turn(session_id="t3", agent="aetheria", user_message="...")
    recorder.record_action(
        round_index=0,
        tool_calls=[
            {"id": "c1", "function": {"name": "broken", "arguments": "{}"}},
            {"id": "c2", "function": {"name": "ok", "arguments": "{}"}},
        ],
        content="",
    )
    recorder.record_observation(round_index=0, results=[
        {"call_id": "c1", "name": "broken", "content": "", "error": "ConnectionError: refused"},
        {"call_id": "c2", "name": "ok", "content": "result", "error": None},
    ])
    path = recorder.finalize(final_content="degraded", finish_reason="stop")
    row = json.loads(path.read_text().strip())
    assert row["telemetry"]["tool_error_count"] == 1


# ─── Append semantics ─────────────────────────────────────────────────────────

def test_two_turns_in_same_session_append_to_same_file(bb: BlackBox):
    """Per-session JSONL: turn 2 appends below turn 1."""
    for i in range(2):
        recorder = bb.begin_turn(session_id="multi", agent="aetheria", user_message=f"q{i}")
        recorder.record_action(
            round_index=0,
            tool_calls=[{"id": f"c{i}", "function": {"name": "search", "arguments": "{}"}}],
            content="",
        )
        recorder.record_observation(round_index=0, results=[
            {"call_id": f"c{i}", "name": "search", "content": "r", "error": None},
        ])
        recorder.finalize(final_content=f"answer{i}", finish_reason="stop")
    path = bb.root / "aetheria" / "multi.jsonl"
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["user_message"] == "q0"
    assert json.loads(lines[1])["user_message"] == "q1"


def test_different_sessions_get_different_files(bb: BlackBox):
    for sid in ("alpha", "beta"):
        recorder = bb.begin_turn(session_id=sid, agent="aetheria", user_message="x")
        recorder.record_action(
            round_index=0,
            tool_calls=[{"id": "c", "function": {"name": "t", "arguments": "{}"}}],
            content="",
        )
        recorder.record_observation(round_index=0, results=[
            {"call_id": "c", "name": "t", "content": "r", "error": None},
        ])
        recorder.finalize(final_content="a", finish_reason="stop")
    assert (bb.root / "aetheria" / "alpha.jsonl").exists()
    assert (bb.root / "aetheria" / "beta.jsonl").exists()


def test_different_agents_get_different_dirs(bb: BlackBox):
    for agent in ("aetheria", "vett", "scotty"):
        recorder = bb.begin_turn(session_id="s", agent=agent, user_message="x")
        recorder.record_action(
            round_index=0,
            tool_calls=[{"id": "c", "function": {"name": "t", "arguments": "{}"}}],
            content="",
        )
        recorder.record_observation(round_index=0, results=[
            {"call_id": "c", "name": "t", "content": "r", "error": None},
        ])
        recorder.finalize(final_content="a", finish_reason="stop")
    assert (bb.root / "aetheria" / "s.jsonl").exists()
    assert (bb.root / "vett" / "s.jsonl").exists()
    assert (bb.root / "scotty" / "s.jsonl").exists()


# ─── Idempotency: finalize twice is harmless ──────────────────────────────────

def test_finalize_is_idempotent(bb: BlackBox):
    recorder = bb.begin_turn(session_id="i", agent="aetheria", user_message="x")
    recorder.record_action(
        round_index=0,
        tool_calls=[{"id": "c", "function": {"name": "t", "arguments": "{}"}}],
        content="",
    )
    recorder.record_observation(round_index=0, results=[
        {"call_id": "c", "name": "t", "content": "r", "error": None},
    ])
    first = recorder.finalize(final_content="a", finish_reason="stop")
    second = recorder.finalize(final_content="a", finish_reason="stop")
    assert first is not None
    assert second is None  # idempotent — second call no-ops
    lines = first.read_text().strip().splitlines()
    assert len(lines) == 1  # only one line was written


# ─── Path-traversal hygiene ───────────────────────────────────────────────────

def test_session_id_path_separators_get_stripped(bb: BlackBox):
    """A malicious or accidental session_id with '/' must not escape the
    per-agent directory (guards against ConversationStore drift writing
    session ids that happen to look like paths)."""
    recorder = bb.begin_turn(
        session_id="../escaped/sid",
        agent="aetheria",
        user_message="x",
    )
    recorder.record_action(
        round_index=0,
        tool_calls=[{"id": "c", "function": {"name": "t", "arguments": "{}"}}],
        content="",
    )
    recorder.record_observation(round_index=0, results=[
        {"call_id": "c", "name": "t", "content": "r", "error": None},
    ])
    path = recorder.finalize(final_content="a", finish_reason="stop")
    assert path is not None
    # The file must live inside bb.root/aetheria/, not above it
    assert bb.root in path.parents
    assert path.parent.name == "aetheria"
