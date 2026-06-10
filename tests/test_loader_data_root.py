"""Tests for EnvConfig.data_root + SOVERYN_DATA_ROOT override.

Path consolidation Task 1: add a single root for all vnext runtime data
so downstream defaults can derive from it.
"""

from pathlib import Path
from soveryn.config.loader import load_env_config, DEFAULT_DATA_ROOT


def test_default_data_root_is_under_soveryn_vnext():
    cfg = load_env_config({})
    assert cfg.data_root == Path.home() / "soveryn_vnext" / "data"
    assert cfg.data_root == DEFAULT_DATA_ROOT


def test_data_root_env_override():
    cfg = load_env_config({"SOVERYN_DATA_ROOT": "/tmp/custom-data"})
    assert cfg.data_root == Path("/tmp/custom-data")


def test_data_root_empty_env_falls_back_to_default():
    cfg = load_env_config({"SOVERYN_DATA_ROOT": ""})
    assert cfg.data_root == DEFAULT_DATA_ROOT
