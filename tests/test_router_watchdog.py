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
