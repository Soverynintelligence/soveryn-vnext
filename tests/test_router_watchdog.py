"""Tests for the router auto-recovery watchdog detection logic.

The watchdog passively scans the soveryn-router journal for the dead-slot
signature (a crashed backend the router keeps proxying to) and decides
whether to restart the router. These tests cover the pure decision
functions; the I/O shell (journalctl/systemctl) is exercised live.
"""
from soveryn.platform.watchdog.router_watchdog import (
    parse_dead_models,
    decide_restart,
    in_cooldown,
    journal_since,
    WINDOW_SECONDS,
    THRESHOLD,
)

GUARDED = {"aetheria", "vett-scotty", "cognition", "embeddings", "reflection"}

# Real dead-slot signature: a proxy line immediately followed by a
# connection error (the router holding a crashed backend's port).
DEAD_AETHERIA = (
    "Jul 03 18:59:21 Soveryn llama-server[2117491]: 223.44.664.446 I srv  "
    "proxy_reques: proxying request to model aetheria on port 58181\n"
    "Jul 03 18:59:21 Soveryn llama-server[2117491]: 223.44.665.325 E srv    "
    "operator(): http client error: Could not establish connection\n"
    "Jul 03 19:29:21 Soveryn llama-server[2117491]: 253.44.664.446 I srv  "
    "proxy_reques: proxying request to model aetheria on port 58181\n"
    "Jul 03 19:29:21 Soveryn llama-server[2117491]: 253.44.665.325 E srv    "
    "operator(): http client error: Could not establish connection\n"
)

HEALTHY = (
    "Jul 04 08:29:33 Soveryn llama-server[2470910]: 19.52.421.179 I srv  "
    "proxy_reques: proxying request to model aetheria on port 47563\n"
    "Jul 04 08:29:44 Soveryn llama-server[2470910]: 20.02.553.313 I srv  "
    "proxy_reques: proxying request to model embeddings on port 43895\n"
)


def test_parse_detects_dead_model_with_error_count():
    counts = parse_dead_models(DEAD_AETHERIA, GUARDED)
    assert counts == {"aetheria": 2}


def test_parse_healthy_log_has_no_dead_models():
    assert parse_dead_models(HEALTHY, GUARDED) == {}


def test_parse_ignores_failed_to_read_which_can_be_a_busy_child():
    # "Failed to read connection" can fire on a healthy-but-busy parallel=1
    # child (read-timeout mid-generation). Counting it would reintroduce the
    # 2026-06-11 busy=broken cascade. Only "Could not establish connection"
    # (dead TCP port) counts.
    text = (
        "x I srv  proxy_reques: proxying request to model vett-scotty on port 5\n"
        "x E srv    operator(): http client error: Failed to read connection\n"
    )
    assert parse_dead_models(text, GUARDED) == {}


def test_parse_ignores_models_not_in_guarded_set():
    # M3 can't load; its connection errors must NOT trigger a restart.
    text = (
        "x I srv  proxy_reques: proxying request to model MiniMax-M3 on port 9\n"
        "x E srv    operator(): http client error: Could not establish connection\n"
        "x I srv  proxy_reques: proxying request to model MiniMax-M3 on port 9\n"
        "x E srv    operator(): http client error: Could not establish connection\n"
    )
    assert parse_dead_models(text, GUARDED) == {}


def test_decide_restart_returns_models_at_or_above_threshold():
    assert decide_restart({"aetheria": 2}, threshold=2) == ["aetheria"]


def test_decide_restart_ignores_single_transient_error():
    assert decide_restart({"aetheria": 1}, threshold=2) == []


def test_in_cooldown_true_within_window():
    assert in_cooldown(last_restart_ts=100.0, now=200.0, cooldown_s=300.0) is True


def test_in_cooldown_false_after_window():
    assert in_cooldown(last_restart_ts=100.0, now=500.0, cooldown_s=300.0) is False


def test_in_cooldown_false_when_never_restarted():
    assert in_cooldown(last_restart_ts=None, now=500.0, cooldown_s=300.0) is False


# ── regression: the 2026-07-26 silent outage ────────────────────────────────
# Aetheria's backend died and the watchdog never fired for 26 hours. Not a bad
# signature and not a bad journal — the lookback was 2 minutes while the ONLY
# caller knocking on the dead slot was the heartbeat, every 1800s. Each window
# saw exactly one error; THRESHOLD wants two. It logged action:"none" 1,500
# times while she was unreachable.
HEARTBEAT_INTERVAL_S = 1800.0


def test_window_spans_enough_heartbeats_to_reach_threshold():
    """The window must be able to hold THRESHOLD heartbeat-spaced errors.

    This is the invariant the outage violated. If the heartbeat interval is ever
    raised above the window, the watchdog silently stops being able to fire.
    """
    needed = (THRESHOLD - 1) * HEARTBEAT_INTERVAL_S
    assert WINDOW_SECONDS > needed, (
        f"window {WINDOW_SECONDS}s cannot hold {THRESHOLD} errors spaced "
        f"{HEARTBEAT_INTERVAL_S}s apart; the watchdog can never reach threshold"
    )


def test_journal_since_defaults_to_full_window():
    assert journal_since(now=10_000.0, last_restart_ts=None,
                         window_s=2400.0) == 7_600.0


def test_journal_since_floors_at_last_restart():
    """Errors older than the last restart are not evidence — they caused it."""
    assert journal_since(now=10_000.0, last_restart_ts=9_500.0,
                         window_s=2400.0) == 9_500.0


def test_journal_since_ignores_restart_older_than_window():
    assert journal_since(now=10_000.0, last_restart_ts=1_000.0,
                         window_s=2400.0) == 7_600.0


def test_no_restart_loop_after_a_restart_clears_the_slot():
    """The widened window must not re-count pre-restart errors once cooldown lapses.

    Without the floor, a 40-minute window would still see the errors that
    triggered the restart and fire again every cooldown period, forever.
    """
    now, restart_at = 10_000.0, 9_900.0
    since = journal_since(now, restart_at, WINDOW_SECONDS)
    assert since == restart_at
    # an error from before the restart falls outside the scanned range
    assert 9_800.0 < since
