"""Tests for soveryn.config.loader — typed env-var config loading."""

import pytest
from pathlib import Path

from soveryn.config import runtime
from soveryn.config.loader import EnvConfig, EnvConfigError, load_env_config


# ─── Defaults ────────────────────────────────────────────────────────────────

def test_defaults_when_no_soveryn_vars():
    """Empty env → all defaults from runtime constants."""
    cfg = load_env_config(env={})
    assert cfg.app_port == runtime.APP_PORT
    assert cfg.model_root == runtime.MODEL_ROOT
    assert cfg.health_timeout_seconds == 2.0


def test_defaults_with_unrelated_env_keys():
    """Unknown env vars (HOME, PATH, etc.) are silently ignored."""
    cfg = load_env_config(env={
        "HOME": "/home/jon",
        "PATH": "/usr/bin:/bin",
        "CONDA_DEFAULT_ENV": "soveryn",
        "SOME_OTHER_TOOL_VAR": "irrelevant",
    })
    assert cfg.app_port == runtime.APP_PORT
    assert cfg.model_root == runtime.MODEL_ROOT
    assert cfg.health_timeout_seconds == 2.0


# ─── Valid overrides ──────────────────────────────────────────────────────────

def test_override_app_port():
    cfg = load_env_config(env={"SOVERYN_APP_PORT": "9000"})
    assert cfg.app_port == 9000


def test_override_model_root():
    cfg = load_env_config(env={"SOVERYN_MODEL_ROOT": "/tmp/models"})
    assert cfg.model_root == Path("/tmp/models")


def test_override_health_timeout():
    cfg = load_env_config(env={"SOVERYN_HEALTH_TIMEOUT": "5.0"})
    assert cfg.health_timeout_seconds == 5.0


def test_override_health_timeout_integer_string():
    """Accept "3" as 3.0 — float("3") works fine."""
    cfg = load_env_config(env={"SOVERYN_HEALTH_TIMEOUT": "3"})
    assert cfg.health_timeout_seconds == 3.0


def test_all_overrides_together():
    cfg = load_env_config(env={
        "SOVERYN_APP_PORT": "7777",
        "SOVERYN_MODEL_ROOT": "/mnt/alt_models",
        "SOVERYN_HEALTH_TIMEOUT": "0.5",
        # unrelated vars are present and must be ignored
        "USER": "jon",
        "SHELL": "/bin/bash",
    })
    assert cfg.app_port == 7777
    assert cfg.model_root == Path("/mnt/alt_models")
    assert cfg.health_timeout_seconds == 0.5


# ─── Parse errors ─────────────────────────────────────────────────────────────

def test_bad_app_port_raises_env_config_error():
    with pytest.raises(EnvConfigError, match="SOVERYN_APP_PORT"):
        load_env_config(env={"SOVERYN_APP_PORT": "not_a_number"})


def test_bad_health_timeout_raises_env_config_error():
    with pytest.raises(EnvConfigError, match="SOVERYN_HEALTH_TIMEOUT"):
        load_env_config(env={"SOVERYN_HEALTH_TIMEOUT": "fast"})


def test_env_config_error_is_value_error():
    """EnvConfigError must subclass ValueError for callers that catch broadly."""
    with pytest.raises(ValueError):
        load_env_config(env={"SOVERYN_APP_PORT": "boom"})


# ─── Empty-string fallback to default ────────────────────────────────────────

def test_empty_string_app_port_uses_default():
    cfg = load_env_config(env={"SOVERYN_APP_PORT": ""})
    assert cfg.app_port == runtime.APP_PORT


def test_empty_string_health_timeout_uses_default():
    cfg = load_env_config(env={"SOVERYN_HEALTH_TIMEOUT": ""})
    assert cfg.health_timeout_seconds == 2.0


def test_empty_string_model_root_uses_default():
    cfg = load_env_config(env={"SOVERYN_MODEL_ROOT": ""})
    assert cfg.model_root == runtime.MODEL_ROOT


# ─── EnvConfig is frozen ──────────────────────────────────────────────────────

def test_env_config_is_frozen():
    cfg = load_env_config(env={})
    with pytest.raises((AttributeError, TypeError)):
        cfg.app_port = 9999  # type: ignore[misc]


# ─── DAEMONS is frozenset ─────────────────────────────────────────────────────

def test_daemons_is_frozenset():
    assert isinstance(runtime.DAEMONS, frozenset)
