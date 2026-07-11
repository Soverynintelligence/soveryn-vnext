"""Test read_presence_candidates tool for Aetheria."""

from soveryn.agents.presence.candidate_store import CandidateStore, Candidate
from soveryn.agents.presence.tools import build_read_presence_candidates_tool


def _c(tid, score=1.0, status="pending"):
    """Helper to create a candidate."""
    return Candidate(tid, "a", "t", "u", "topic", score, status, "2026-07-09T00:00:00")


def test_read_presence_candidates_tool(tmp_path):
    """Test that build_read_presence_candidates_tool creates a valid ToolSpec."""
    # Setup: create store with 2 pending candidates
    store = CandidateStore(tmp_path / "c.db")
    store.upsert(_c("1", score=1.0))
    store.upsert(_c("2", score=5.0))

    # Build the tool
    spec = build_read_presence_candidates_tool(store=store)

    # Assert spec properties
    assert spec.owner == "aetheria"
    assert spec.name == "read_presence_candidates"

    # Invoke handler with empty args (uses default limit)
    result = spec.handler({})

    # Verify result is a list of dicts, ranked by score
    assert isinstance(result, list)
    assert len(result) == 2
    # Higher score first (5.0 before 1.0)
    assert result[0]["tweet_id"] == "2"
    assert result[0]["score"] == 5.0
    assert result[1]["tweet_id"] == "1"
    assert result[1]["score"] == 1.0


def test_read_presence_candidates_tool_with_limit(tmp_path):
    """Test that limit parameter works."""
    store = CandidateStore(tmp_path / "c.db")
    store.upsert(_c("1", score=1.0))
    store.upsert(_c("2", score=5.0))
    store.upsert(_c("3", score=3.0))

    spec = build_read_presence_candidates_tool(store=store)

    # Invoke with limit=2
    result = spec.handler({"limit": 2})

    assert len(result) == 2
    assert result[0]["tweet_id"] == "2"  # score 5.0
    assert result[1]["tweet_id"] == "3"  # score 3.0
