"""Tests for soveryn.agents.dream.config — frozen dataclass + from_env()."""

from soveryn.agents.dream.config import DreamConfig


def test_from_env_uses_defaults_when_unset():
    cfg = DreamConfig.from_env({})
    assert cfg.enabled is True
    assert cfg.dry_run is True
    assert cfg.quiet_hours == "23:00-07:00"
    assert cfg.activity_backoff_seconds == 1800
    assert cfg.nodes_per_run == 300
    assert cfg.max_internal_iterations == 3
    assert cfg.cognition_url == "http://127.0.0.1:8089"
    assert cfg.cognition_timeout_seconds == 120


def test_from_env_parses_overrides():
    env = {
        "SOVERYN_DREAM_ENABLED": "false",
        "SOVERYN_DREAM_DRY_RUN": "false",
        "SOVERYN_DREAM_QUIET_HOURS": "00:00-06:00",
        "SOVERYN_DREAM_ACTIVITY_BACKOFF_SECONDS": "600",
        "SOVERYN_DREAM_NODES_PER_RUN": "500",
        "SOVERYN_DREAM_MAX_INTERNAL_ITERATIONS": "5",
        "SOVERYN_DREAM_COGNITION_URL": "http://127.0.0.1:9999",
        "SOVERYN_DREAM_COGNITION_TIMEOUT_SECONDS": "60",
    }
    cfg = DreamConfig.from_env(env)
    assert cfg.enabled is False
    assert cfg.dry_run is False
    assert cfg.quiet_hours == "00:00-06:00"
    assert cfg.activity_backoff_seconds == 600
    assert cfg.nodes_per_run == 500
    assert cfg.max_internal_iterations == 5
    assert cfg.cognition_url == "http://127.0.0.1:9999"
    assert cfg.cognition_timeout_seconds == 60


def test_from_env_dry_run_defaults_true():
    """Critical: dry-run defaults TRUE at deploy. Spec section 'Configuration'."""
    cfg = DreamConfig.from_env({})
    assert cfg.dry_run is True
