"""Test CandidateStore: dedup, ranking, posted-id ledger."""

from soveryn.agents.presence.candidate_store import CandidateStore, Candidate


def _c(tid, score=1.0, status="pending"):
    return Candidate(tid, "a", "t", "u", "topic", score, status, "2026-07-09T00:00:00")


def test_dedup_and_seen(tmp_path):
    s = CandidateStore(tmp_path / "c.db")
    assert not s.is_seen("1")
    s.upsert(_c("1"))
    assert s.is_seen("1")


def test_pending_ranked_by_score(tmp_path):
    s = CandidateStore(tmp_path / "c.db")
    s.upsert(_c("1", score=1.0))
    s.upsert(_c("2", score=5.0))
    assert [c.tweet_id for c in s.pending_ranked(10)] == ["2", "1"]


def test_posted_id_counts_as_seen(tmp_path):
    s = CandidateStore(tmp_path / "c.db")
    s.record_posted_id("42")
    assert s.is_seen("42")  # our own post never re-ingested as a fresh mention
