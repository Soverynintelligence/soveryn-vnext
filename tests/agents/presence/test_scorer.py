import pytest
from soveryn.agents.presence.scorer import score_tweet
from soveryn.agents.presence.x_client import Tweet
from soveryn.agents.presence.config import PresenceConfig


CFG = PresenceConfig.default()


def test_niche_match_scores_per_term():
    """Two distinct niche terms should score >= 2.0"""
    t = Tweet("1", "a", "thoughts on sovereign AI and local LLM reliability", "u")
    assert score_tweet(t, CFG) >= 2.0


def test_mention_gets_boost_even_without_niche():
    """Mention should boost score by 3.0 even without niche terms"""
    t = Tweet("2", "a", "hey @Soveryn_AI what do you think?", "u")
    assert score_tweet(t, CFG, is_mention=True) >= 3.0


def test_offtopic_scores_zero():
    """Off-topic tweet with no mention should score 0.0"""
    assert score_tweet(Tweet("3", "a", "my lunch was great", "u"), CFG) == 0.0


def test_single_niche_term():
    """Single niche term match should score 1.0"""
    t = Tweet("4", "a", "sovereign AI is the future", "u")
    assert score_tweet(t, CFG) == 1.0


def test_case_insensitive_matching():
    """Niche term matching should be case-insensitive"""
    t = Tweet("5", "a", "SOVEREIGN AI and LOCAL LLM", "u")
    assert score_tweet(t, CFG) >= 2.0


def test_duplicate_terms_counted_once():
    """Duplicate niche terms in same tweet count only once"""
    t = Tweet("6", "a", "sovereign AI sovereign AI and local LLM local LLM", "u")
    # Should be 2 distinct terms, not 4
    assert score_tweet(t, CFG) == 2.0


def test_mention_with_niche_terms():
    """Mention boost should add to niche term score"""
    t = Tweet("7", "a", "@Soveryn_AI thoughts on sovereign AI", "u")
    # 1 niche term + 3.0 mention boost = 4.0
    assert score_tweet(t, CFG, is_mention=True) == 4.0


def test_recency_bonus_with_timestamps():
    """Recency bonus up to 1.0 for tweets < 6h old"""
    now_ts = 1000.0
    tweet_ts = 900.0  # 100 seconds old
    t = Tweet("8", "a", "sovereign AI is great", "u")
    score = score_tweet(t, CFG, now_ts=now_ts, tweet_ts=tweet_ts)
    # 1.0 for term + recency bonus (0.986 for 100s / 21600s)
    assert 1.0 < score < 2.0
    assert score > 1.98  # Very fresh tweet should get nearly full bonus


def test_recency_bonus_older_than_6h():
    """Recency bonus should not apply to tweets > 6h old"""
    now_ts = 1000.0
    tweet_ts = 1000.0 - 6 * 3600  # Exactly 6h old
    t = Tweet("9", "a", "sovereign AI", "u")
    score = score_tweet(t, CFG, now_ts=now_ts, tweet_ts=tweet_ts)
    # No recency bonus for 6h+ old tweets
    assert score == 1.0


def test_recency_bonus_only_with_both_timestamps():
    """Recency bonus only applies when both now_ts and tweet_ts provided"""
    t = Tweet("10", "a", "sovereign AI", "u")
    # No timestamps
    score1 = score_tweet(t, CFG)
    assert score1 == 1.0
    # Only one timestamp - should not apply recency bonus
    score2 = score_tweet(t, CFG, now_ts=1000.0)
    assert score2 == 1.0
    # Only tweet_ts - should not apply recency bonus
    score3 = score_tweet(t, CFG, tweet_ts=900.0)
    assert score3 == 1.0


def test_offtopic_mention_gets_boost():
    """Mention boost applies even if tweet is off-topic"""
    t = Tweet("11", "a", "@Soveryn_AI my lunch was great", "u")
    assert score_tweet(t, CFG, is_mention=True) == 3.0


def test_multiple_niche_terms_no_duplicates():
    """Multiple distinct niche terms score additively"""
    t = Tweet("12", "a", "on-device AI open-weight models AI companions", "u")
    # 3 distinct terms
    assert score_tweet(t, CFG) == 3.0


def test_substring_matching():
    """Niche terms match as substrings (case-insensitive)"""
    t = Tweet("13", "a", "I love local LLMs in my app", "u")
    # "local LLM" should match "local LLMs"
    assert score_tweet(t, CFG) >= 1.0
