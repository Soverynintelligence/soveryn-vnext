"""Digest — density-capped, qualitative one-line X digest for heartbeat wake."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soveryn.agents.presence.candidate_store import CandidateStore


def build_digest(store: CandidateStore, *, top_n: int = 3) -> str | None:
    """Build a density-capped, qualitative one-line X digest.

    Args:
        store: CandidateStore exposing pending_ranked(limit) -> list[Candidate].
        top_n: Number of top items to name explicitly (default 3).

    Returns:
        A single, qualitative line summarizing new X activity, e.g.,
        "X: a few new mentions, one thread on local-LLM reliability."
        or None if the feed is empty (omit the line entirely).

    Constraints:
        - No directive language ("you should", "consider", etc.).
        - No raw firehose counts (never "50 new mentions").
        - Density-capped: even with 50+ candidates, names at most top_n and
          buckets the rest with qualitative count language ("several", "more").
        - Output is always a single sentence ending with a period.
    """
    # Fetch all pending candidates, but cap the initial query at a reasonable limit
    # to avoid loading huge lists; we only need enough to decide top_n + bucket.
    candidates = store.pending_ranked(limit=100)

    if not candidates:
        return None

    # Group candidates by kind (mention, topic, reply, etc.)
    by_kind = {}
    for c in candidates:
        if c.kind not in by_kind:
            by_kind[c.kind] = []
        by_kind[c.kind].append(c)

    # Build the output: name the top_n candidates, then bucket the rest.
    named_items = []
    total_named = 0

    # Sort by score to ensure we pick the highest-scoring items
    # (candidates are already ranked by pending_ranked, but let's be explicit)
    sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)

    # Extract top_n items by score
    top_candidates = sorted_candidates[:top_n]
    remainder_count = len(candidates) - len(top_candidates)

    for i, c in enumerate(top_candidates):
        # Name the item qualitatively by kind; extract a brief topic from text if possible
        if c.kind == "mention":
            item_label = "mention"
        elif c.kind == "topic":
            # Try to extract a brief topic from the text (first ~10 words or until natural break)
            words = c.text.split()[:10]
            brief_topic = " ".join(words).lower()
            # Clean up common phrases
            brief_topic = brief_topic.replace("thread on ", "").replace("discussion on ", "")
            # For topics, use article + topic
            item_label = f"thread on {brief_topic}"
        else:
            # Default for other kinds
            item_label = c.kind

        named_items.append(item_label)
        total_named += 1

    # Build the line
    parts = []

    # If we have multiple named items, join them
    if len(named_items) == 1:
        parts.append(named_items[0])
    elif len(named_items) == 2:
        parts.append(f"{named_items[0]}, {named_items[1]}")
    elif len(named_items) > 2:
        # Oxford comma
        parts.append(", ".join(named_items[:-1]) + f", and {named_items[-1]}")

    # Add qualitative count for the remainder
    if remainder_count > 0:
        remainder_label = _qualitative_count(remainder_count)
        if parts:
            parts.append(f", {remainder_label}")
        else:
            parts.append(remainder_label)

    line = "".join(parts)

    # Ensure it's a proper sentence
    if line and not line.endswith("."):
        line += "."

    return line if line else None


def _qualitative_count(n: int) -> str:
    """Convert a count to qualitative language.

    Args:
        n: Number of items.

    Returns:
        Qualitative descriptor (e.g., "a few more", "several more", "many more").
    """
    if n <= 2:
        return "a couple more"
    elif n <= 5:
        return "a few more"
    elif n <= 15:
        return "several more"
    else:
        return "many more"
