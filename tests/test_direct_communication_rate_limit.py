import pytest
from datetime import datetime, timedelta
from soveryn.agents.direct_communication.rate_limit import DirectCommRateLimiter


def test_under_cap_when_no_calls_recorded():
    limiter = DirectCommRateLimiter(per_minute_cap=8)
    now = datetime(2026, 6, 5, 12, 0, 0)
    assert limiter.under_cap(sender="aetheria", target="vett", now=now)


def test_under_cap_until_cap_reached():
    limiter = DirectCommRateLimiter(per_minute_cap=3)
    now = datetime(2026, 6, 5, 12, 0, 0)
    for _ in range(3):
        limiter.record(sender="aetheria", target="vett", now=now)
    assert not limiter.under_cap(sender="aetheria", target="vett", now=now)


def test_independent_caps_per_sender_target_pair():
    """Aetheria → Vett at cap shouldn't block Aetheria → Scotty."""
    limiter = DirectCommRateLimiter(per_minute_cap=2)
    now = datetime(2026, 6, 5, 12, 0, 0)
    for _ in range(2):
        limiter.record(sender="aetheria", target="vett", now=now)
    assert limiter.under_cap(sender="aetheria", target="scotty", now=now)


def test_cap_resets_after_minute_window():
    limiter = DirectCommRateLimiter(per_minute_cap=2)
    t0 = datetime(2026, 6, 5, 12, 0, 0)
    for _ in range(2):
        limiter.record(sender="aetheria", target="vett", now=t0)
    t1 = t0 + timedelta(seconds=61)
    assert limiter.under_cap(sender="aetheria", target="vett", now=t1)


def test_retry_after_seconds_when_capped():
    """When over cap, calculate seconds until oldest call falls out of window."""
    limiter = DirectCommRateLimiter(per_minute_cap=1)
    t0 = datetime(2026, 6, 5, 12, 0, 0)
    limiter.record(sender="aetheria", target="vett", now=t0)
    t1 = t0 + timedelta(seconds=15)
    retry_after = limiter.seconds_until_under_cap(
        sender="aetheria", target="vett", now=t1,
    )
    assert retry_after == 45  # 60 - 15


def test_seconds_until_under_cap_handles_per_minute_cap_zero():
    """Degenerate state: cap=0 + empty deque. under_cap is False (0 < 0),
    so seconds_until_under_cap is called — but the deque is empty so
    q[0] would crash. Regression: returns window length so the caller's
    retry loop paces itself instead of busy-looping or crashing."""
    limiter = DirectCommRateLimiter(per_minute_cap=0)
    now = datetime(2026, 6, 5, 12, 0, 0)
    # Sanity: under_cap is False at cap=0 (the caller's prerequisite)
    assert not limiter.under_cap(sender="aetheria", target="vett", now=now)
    # Should NOT crash; should return a sane retry value
    retry = limiter.seconds_until_under_cap(
        sender="aetheria", target="vett", now=now,
    )
    assert retry == 60  # window length — the longest reasonable pacing
