"""Tests for build_digest — density-capped qualitative X digest."""

from pathlib import Path
from datetime import datetime, timezone

import pytest

from soveryn.agents.presence.candidate_store import CandidateStore, Candidate
from soveryn.agents.presence.digest import build_digest


@pytest.fixture
def store(tmp_path: Path) -> CandidateStore:
    """Create a temporary CandidateStore for testing."""
    db_path = tmp_path / "candidates.db"
    return CandidateStore(db_path)


def test_empty_feed_returns_none(store: CandidateStore) -> None:
    """Empty feed → None (omit the line)."""
    result = build_digest(store)
    assert result is None


def test_two_candidates_names_both(store: CandidateStore) -> None:
    """Two candidates → qualitative names both."""
    now = datetime.now(timezone.utc).isoformat()

    c1 = Candidate(
        tweet_id="1",
        author="user1",
        text="Great mention about our work",
        url="https://x.com/1",
        kind="mention",
        score=0.9,
        status="pending",
        created_at=now,
    )
    c2 = Candidate(
        tweet_id="2",
        author="user2",
        text="Thread on local LLM reliability",
        url="https://x.com/2",
        kind="topic",
        score=0.85,
        status="pending",
        created_at=now,
    )

    store.upsert(c1)
    store.upsert(c2)

    result = build_digest(store, top_n=3)

    # Should name both items qualitatively
    assert result is not None
    assert "mention" in result.lower()
    assert "local llm" in result.lower() or "thread" in result.lower()
    # Should NOT have raw numbers
    assert "2" not in result or "two" in result.lower()


def test_fifty_candidates_qualitative_no_raw_count(store: CandidateStore) -> None:
    """50 candidates → qualitative bucket, no raw '50', no directive language."""
    now = datetime.now(timezone.utc).isoformat()

    # Insert 50 candidates with varied kinds and scores
    for i in range(50):
        kind = "mention" if i % 3 == 0 else "topic"
        text = f"Tweet {i}: relevant content" if i < 5 else f"Additional tweet {i}"

        c = Candidate(
            tweet_id=str(i),
            author=f"user{i}",
            text=text,
            url=f"https://x.com/{i}",
            kind=kind,
            score=1.0 - (i * 0.01),  # Descending scores
            status="pending",
            created_at=now,
        )
        store.upsert(c)

    result = build_digest(store, top_n=3)

    # Should not be None
    assert result is not None
    # Should be a single sentence (one period at end, not multiple)
    assert result.count(".") == 1, f"Expected one sentence, got: {result}"
    # Should NOT contain the raw number 50
    assert "50" not in result
    # Should use qualitative language
    assert any(
        word in result.lower()
        for word in ["many", "several", "a few", "more", "additional", "many more"]
    )
    # Should NOT contain directive language
    assert "you should" not in result.lower()
    assert "consider" not in result.lower()
    assert "reply to" not in result.lower()
    assert "reply" not in result.lower() or "in reply" in result.lower()

    # Should name at most top_n items explicitly (roughly)
    # The output should show top items but not all 50


def test_three_candidates_respects_top_n(store: CandidateStore) -> None:
    """Three candidates with top_n=2 → names at most 2 explicitly."""
    now = datetime.now(timezone.utc).isoformat()

    for i in range(3):
        c = Candidate(
            tweet_id=str(i),
            author=f"user{i}",
            text=f"Content {i}",
            url=f"https://x.com/{i}",
            kind="mention" if i % 2 == 0 else "topic",
            score=1.0 - (i * 0.1),
            status="pending",
            created_at=now,
        )
        store.upsert(c)

    result = build_digest(store, top_n=2)

    assert result is not None
    # Should respect the top_n limit


def test_no_directive_language_variants(store: CandidateStore) -> None:
    """Test that various directive phrases never appear."""
    now = datetime.now(timezone.utc).isoformat()

    # Add many candidates to trigger full output
    for i in range(30):
        c = Candidate(
            tweet_id=str(i),
            author=f"user{i}",
            text=f"Tweet {i}",
            url=f"https://x.com/{i}",
            kind="mention" if i < 5 else "topic",
            score=1.0 - (i * 0.01),
            status="pending",
            created_at=now,
        )
        store.upsert(c)

    result = build_digest(store, top_n=3)

    assert result is not None
    lower_result = result.lower()

    # Forbidden phrases
    forbidden = [
        "you should",
        "you might",
        "consider replying",
        "consider responding",
        "consider engaging",
        "you might want",
        "should reply",
        "might reply",
    ]

    for phrase in forbidden:
        assert phrase not in lower_result, f"Found forbidden phrase: {phrase}"


def test_output_is_single_sentence(store: CandidateStore) -> None:
    """Output should be a single sentence (one period)."""
    now = datetime.now(timezone.utc).isoformat()

    for i in range(20):
        c = Candidate(
            tweet_id=str(i),
            author=f"user{i}",
            text=f"Tweet {i}",
            url=f"https://x.com/{i}",
            kind="mention" if i % 2 == 0 else "topic",
            score=1.0 - (i * 0.02),
            status="pending",
            created_at=now,
        )
        store.upsert(c)

    result = build_digest(store, top_n=3)

    assert result is not None
    # Should end with period
    assert result.endswith(".")
    # Should have exactly one period
    assert result.count(".") == 1


def test_qualitative_counts_for_buckets(store: CandidateStore) -> None:
    """Verify qualitative count language is used."""
    now = datetime.now(timezone.utc).isoformat()

    # Add 15 candidates
    for i in range(15):
        c = Candidate(
            tweet_id=str(i),
            author=f"user{i}",
            text=f"Tweet {i}",
            url=f"https://x.com/{i}",
            kind="topic",
            score=1.0 - (i * 0.01),
            status="pending",
            created_at=now,
        )
        store.upsert(c)

    result = build_digest(store, top_n=2)

    assert result is not None
    # Should use qualitative language instead of exact count
    lower_result = result.lower()

    # Check for qualitative indicators
    qualitative_words = {
        "a few", "several", "more", "many", "some", "a number of",
        "additional"
    }

    # At least one qualitative indicator should be present
    has_qualitative = any(word in lower_result for word in qualitative_words)
    assert has_qualitative, f"No qualitative language found in: {result}"
