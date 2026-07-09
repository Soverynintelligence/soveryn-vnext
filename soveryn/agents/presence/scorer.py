"""Pure relevance scorer for tweets based on niche terms, mention status, and recency."""

from soveryn.agents.presence.x_client import Tweet
from soveryn.agents.presence.config import PresenceConfig


def score_tweet(
    tweet: Tweet,
    cfg: PresenceConfig,
    *,
    is_mention: bool = False,
    now_ts: float | None = None,
    tweet_ts: float | None = None,
) -> float:
    """
    Score a tweet for relevance to the @Soveryn_AI niche.

    Pure function (no I/O, no global state mutation).

    Scoring:
    - +1.0 per distinct niche term matched (case-insensitive substring match)
    - +3.0 if is_mention=True
    - +0.0 to +1.0 recency bonus for tweets < 6h old (only when both timestamps provided)
    - Returns 0.0 when nothing matches and not a mention

    Args:
        tweet: The tweet to score
        cfg: Presence config with niche_terms tuple
        is_mention: Whether this tweet mentions @Soveryn_AI
        now_ts: Current timestamp (seconds since epoch), required for recency bonus
        tweet_ts: Tweet timestamp (seconds since epoch), required for recency bonus

    Returns:
        Float score >= 0.0
    """
    tweet_text_lower = tweet.text.lower()

    # Count distinct niche terms matched (substring match, case-insensitive)
    matched_terms = set()
    for term in cfg.niche_terms:
        if term.lower() in tweet_text_lower:
            matched_terms.add(term)

    niche_score = float(len(matched_terms))

    # Mention boost
    mention_boost = 3.0 if is_mention else 0.0

    # Recency bonus (only when both timestamps provided)
    recency_bonus = 0.0
    if now_ts is not None and tweet_ts is not None:
        age_seconds = now_ts - tweet_ts
        six_hours_seconds = 6 * 3600  # 21600 seconds

        if age_seconds < six_hours_seconds:
            # Linear recency bonus: 1.0 at age 0, 0.0 at age 6h
            recency_bonus = max(0.0, 1.0 - (age_seconds / six_hours_seconds))

    total_score = niche_score + mention_boost + recency_bonus

    # Return 0.0 if nothing matched and not a mention
    if total_score == 0.0:
        return 0.0

    return total_score
