"""Tests for Aetheria's read_x + post_to_x tools.

Trust-stage gating on post_to_x is the load-bearing behavior here: Stage 0
must NEVER call the publisher, Stage 1 gates only replies, Stage 2 always
publishes, and a missing/malformed trust file must fail closed to Stage 0
(never a higher stage).
"""

from __future__ import annotations

import pytest

from soveryn.agents.presence.candidate_store import Candidate, CandidateStore
from soveryn.agents.presence.staged_store import StagedStore
from soveryn.agents.presence.trust import set_trust_stage
from soveryn.agents.aetheria.tools.x_tools import (
    BUSY_MESSAGE,
    STAGED_MESSAGE,
    build_post_to_x_tool,
    build_read_x_tool,
)


FIXED_NOW = "2026-07-11T12:00:00"


def fixed_now_fn() -> str:
    return FIXED_NOW


class RecordingPublisher:
    """Fake publisher_fn that records calls and returns a canned result."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, text: str, *, reply_to: str | None = None):
        self.calls.append({"text": text, "reply_to": reply_to})
        return {"id": "posted-123", "url": "https://x.com/Soveryn_AI/status/posted-123"}


# ---------------------------------------------------------------------------
# read_x
# ---------------------------------------------------------------------------


def test_read_x_tool_spec_shape(tmp_path):
    store = CandidateStore(tmp_path / "candidates.db")
    spec = build_read_x_tool(store=store)
    assert spec.name == "read_x"
    assert spec.owner == "aetheria"
    assert spec.schema["additionalProperties"] is False
    assert "limit" in spec.schema["properties"]


def test_read_x_returns_honest_empty_list_when_nothing_queued(tmp_path):
    store = CandidateStore(tmp_path / "candidates.db")
    spec = build_read_x_tool(store=store)
    result = spec.handler({})
    assert result == []


def test_read_x_returns_ranked_candidates_as_dicts(tmp_path):
    store = CandidateStore(tmp_path / "candidates.db")
    store.upsert(
        Candidate(
            tweet_id="1",
            author="someone",
            text="low score",
            url="https://x.com/1",
            kind="mention",
            score=0.2,
            status="pending",
            created_at=FIXED_NOW,
        )
    )
    store.upsert(
        Candidate(
            tweet_id="2",
            author="someone_else",
            text="high score",
            url="https://x.com/2",
            kind="mention",
            score=0.9,
            status="pending",
            created_at=FIXED_NOW,
        )
    )
    spec = build_read_x_tool(store=store)
    result = spec.handler({})
    assert isinstance(result, list)
    assert [r["tweet_id"] for r in result] == ["2", "1"]
    assert result[0] == {
        "tweet_id": "2",
        "author": "someone_else",
        "text": "high score",
        "url": "https://x.com/2",
        "kind": "mention",
        "score": 0.9,
        "status": "pending",
        "created_at": FIXED_NOW,
    }


def test_read_x_respects_limit_arg(tmp_path):
    store = CandidateStore(tmp_path / "candidates.db")
    for i in range(5):
        store.upsert(
            Candidate(
                tweet_id=str(i),
                author="a",
                text=f"text {i}",
                url="",
                kind="topic",
                score=float(i),
                status="pending",
                created_at=FIXED_NOW,
            )
        )
    spec = build_read_x_tool(store=store)
    result = spec.handler({"limit": 2})
    assert len(result) == 2


# ---------------------------------------------------------------------------
# post_to_x — fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def staged(tmp_path):
    return StagedStore(tmp_path / "staged.db")


@pytest.fixture
def trust_path(tmp_path):
    return tmp_path / "x_trust.json"


@pytest.fixture
def publisher():
    return RecordingPublisher()


def make_post_to_x_tool(staged, publisher, trust_path):
    return build_post_to_x_tool(
        staged=staged,
        publisher_fn=publisher,
        trust_path=trust_path,
        now_fn=fixed_now_fn,
    )


def test_post_to_x_spec_shape(staged, publisher, trust_path):
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    assert spec.name == "post_to_x"
    assert spec.owner == "aetheria"
    assert spec.schema["required"] == ["text"]
    assert spec.schema["additionalProperties"] is False


# --- Stage 0: everything stages, publisher never called ---


def test_stage0_original_post_stages_not_published(staged, publisher, trust_path):
    set_trust_stage(trust_path, 0)
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    result = spec.handler({"text": "hello world"})
    assert result == {"status": "staged", "message": STAGED_MESSAGE}
    assert publisher.calls == []
    pending = staged.pending("aetheria")
    assert pending is not None
    assert pending.text == "hello world"
    assert pending.reply_to is None


def test_stage0_reply_stages_not_published(staged, publisher, trust_path):
    set_trust_stage(trust_path, 0)
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    result = spec.handler({"text": "a reply", "reply_to": "999"})
    assert result == {"status": "staged", "message": STAGED_MESSAGE}
    assert publisher.calls == []
    pending = staged.pending("aetheria")
    assert pending is not None
    assert pending.reply_to == "999"


def test_stage0_second_post_while_one_staged_returns_busy(staged, publisher, trust_path):
    set_trust_stage(trust_path, 0)
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    first = spec.handler({"text": "first"})
    assert first["status"] == "staged"
    second = spec.handler({"text": "second"})
    assert second == {"status": "busy", "message": BUSY_MESSAGE}
    assert publisher.calls == []
    # still only the first post is pending
    pending = staged.pending("aetheria")
    assert pending.text == "first"


# --- Stage 1: replies gated, originals autonomous ---


def test_stage1_reply_stages(staged, publisher, trust_path):
    set_trust_stage(trust_path, 1)
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    result = spec.handler({"text": "a reply", "reply_to": "42"})
    assert result == {"status": "staged", "message": STAGED_MESSAGE}
    assert publisher.calls == []
    assert staged.pending("aetheria") is not None


def test_stage1_original_publishes_immediately(staged, publisher, trust_path):
    set_trust_stage(trust_path, 1)
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    result = spec.handler({"text": "an original thought"})
    assert result["status"] == "posted"
    assert publisher.calls == [{"text": "an original thought", "reply_to": None}]
    assert staged.pending("aetheria") is None


# --- Stage 2: fully autonomous ---


def test_stage2_original_publishes_immediately(staged, publisher, trust_path):
    set_trust_stage(trust_path, 2)
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    result = spec.handler({"text": "an original thought"})
    assert result["status"] == "posted"
    assert publisher.calls == [{"text": "an original thought", "reply_to": None}]
    assert staged.pending("aetheria") is None


def test_stage2_reply_publishes_immediately(staged, publisher, trust_path):
    set_trust_stage(trust_path, 2)
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    result = spec.handler({"text": "a reply", "reply_to": "42"})
    assert result["status"] == "posted"
    assert publisher.calls == [{"text": "a reply", "reply_to": "42"}]
    assert staged.pending("aetheria") is None


# --- fail-closed: missing/malformed trust file behaves as Stage 0 ---


def test_missing_trust_file_treated_as_stage0(staged, publisher, tmp_path):
    trust_path = tmp_path / "does_not_exist.json"
    assert not trust_path.exists()
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    result = spec.handler({"text": "an original thought"})
    assert result["status"] == "staged"
    assert publisher.calls == []


def test_malformed_trust_file_treated_as_stage0(staged, publisher, trust_path):
    trust_path.write_text("{ not valid json")
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    result = spec.handler({"text": "an original thought"})
    assert result["status"] == "staged"
    assert publisher.calls == []


def test_trust_file_read_fresh_each_call_panic_takes_effect_next_call(staged, publisher, trust_path):
    set_trust_stage(trust_path, 2)
    spec = make_post_to_x_tool(staged, publisher, trust_path)
    result = spec.handler({"text": "first, autonomous"})
    assert result["status"] == "posted"

    # panic mid-session
    set_trust_stage(trust_path, 0)
    result2 = spec.handler({"text": "second, after panic"})
    assert result2["status"] == "staged"
    assert publisher.calls == [{"text": "first, autonomous", "reply_to": None}]


# --- publisher failure surfaces as a friendly dict, never raises ---


def test_publish_failure_returns_friendly_error_dict(staged, trust_path):
    def failing_publisher(text, *, reply_to=None):
        raise RuntimeError("X API is down")

    set_trust_stage(trust_path, 2)
    spec = build_post_to_x_tool(
        staged=staged,
        publisher_fn=failing_publisher,
        trust_path=trust_path,
        now_fn=fixed_now_fn,
    )
    result = spec.handler({"text": "will fail"})
    assert result["status"] == "error"
    assert "X API is down" in result["message"]
