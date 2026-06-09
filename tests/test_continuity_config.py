"""Tests for soveryn.platform.continuity.config.

Covers Task 1 of the Cross-Surface Continuity plan: defaults, env-var
parsing, the locked autonomous-prefix table (including the load-bearing
negative assertion that [signal] is NOT in the set), and the
session_is_autonomous helper.
"""

from __future__ import annotations

import pytest

from soveryn.platform.continuity import (
    AUTONOMOUS_SESSION_PREFIXES,
    ContinuityConfig,
    DEFAULT_PER_SESSION_CAP,
    DEFAULT_TOKEN_BUDGET,
    DEFAULT_WINDOW_HOURS,
)


def test_default_config_matches_spec():
    cfg = ContinuityConfig.from_env({})
    assert cfg.enabled is True
    assert cfg.window_hours == 6
    assert cfg.token_budget == 1500
    assert cfg.per_session_cap == 400
    assert cfg.window_hours == DEFAULT_WINDOW_HOURS
    assert cfg.token_budget == DEFAULT_TOKEN_BUDGET
    assert cfg.per_session_cap == DEFAULT_PER_SESSION_CAP


def test_env_overrides_apply():
    cfg = ContinuityConfig.from_env({
        "SOVERYN_CROSS_SURFACE_WINDOW_HOURS": "4",
        "SOVERYN_CROSS_SURFACE_TOKEN_BUDGET": "2000",
        "SOVERYN_CROSS_SURFACE_ENABLED": "false",
    })
    assert cfg.window_hours == 4
    assert cfg.token_budget == 2000
    assert cfg.enabled is False


@pytest.mark.parametrize(
    "raw, want",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("", True),
    ],
)
def test_enabled_flag_accepts_truthy_strings(raw, want):
    cfg = ContinuityConfig.from_env({"SOVERYN_CROSS_SURFACE_ENABLED": raw})
    assert cfg.enabled is want, f"raw={raw!r}"


def test_autonomous_prefixes_locked_set():
    """Signal MUST NOT be in this set — Signal is a real rail with Jon."""
    assert "[heartbeat]" in AUTONOMOUS_SESSION_PREFIXES
    assert "[patrol]" in AUTONOMOUS_SESSION_PREFIXES
    assert "[webhook]" in AUTONOMOUS_SESSION_PREFIXES
    assert "[dream]" in AUTONOMOUS_SESSION_PREFIXES
    assert "[salience-smoke]" in AUTONOMOUS_SESSION_PREFIXES
    assert "[signal]" not in AUTONOMOUS_SESSION_PREFIXES
    assert set(AUTONOMOUS_SESSION_PREFIXES) == {
        "[heartbeat]",
        "[patrol]",
        "[webhook]",
        "[dream]",
        "[salience-smoke]",
    }


def test_session_is_autonomous_method():
    cfg = ContinuityConfig()
    assert cfg.session_is_autonomous(None) is False
    assert cfg.session_is_autonomous("") is False
    assert cfg.session_is_autonomous("[heartbeat] aetheria") is True
    assert cfg.session_is_autonomous("[patrol] vett 2026-06-09") is True
    assert cfg.session_is_autonomous("[webhook] github-push") is True
    assert cfg.session_is_autonomous("[dream] consolidation") is True
    assert cfg.session_is_autonomous("[salience-smoke] fixture") is True
    # Signal is a real rail — must be treated as non-autonomous
    assert cfg.session_is_autonomous("[signal] aetheria +19102489392") is False
    # Arbitrary user-titled sessions are not autonomous
    assert cfg.session_is_autonomous("debugging the recall pipeline") is False
    assert cfg.session_is_autonomous("untitled") is False


def test_per_session_cap_env_override():
    cfg = ContinuityConfig.from_env({
        "SOVERYN_CROSS_SURFACE_PER_SESSION_CAP": "250",
    })
    assert cfg.per_session_cap == 250
    # Other fields stay on defaults
    assert cfg.enabled is True
    assert cfg.window_hours == DEFAULT_WINDOW_HOURS
    assert cfg.token_budget == DEFAULT_TOKEN_BUDGET
