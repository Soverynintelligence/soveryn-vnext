"""Tests for the X feed worker launcher (soveryn/agents/x_feed/__main__.py).

Follows the TDD pattern: parse_args handles defaults/flags; build_worker
assembles components with monkeypatched env + faked XClient.from_env to
ensure no network calls. The worker itself (XFeedWorker) is tested in
tests/agents/presence/test_feed_worker.py; this test only verifies the
launcher machinery.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import soveryn.agents.x_feed.__main__ as launch
from soveryn.agents.presence.feed_worker import XFeedWorker


def test_parse_args_defaults():
    """parse_args with no flags uses documented defaults."""
    args = launch.parse_args([])
    assert args == launch.LauncherArgs()
    assert args.interval_seconds == launch.DEFAULT_INTERVAL_SECONDS
    assert args.iterations is None


def test_parse_args_interval_seconds_override():
    """parse_args --interval-seconds accepts a float."""
    args = launch.parse_args(["--interval-seconds", "123.45"])
    assert args.interval_seconds == 123.45


def test_parse_args_iterations_override():
    """parse_args --iterations accepts a positive int."""
    args = launch.parse_args(["--iterations", "5"])
    assert args.iterations == 5


def test_parse_args_combined():
    """parse_args accepts multiple flags together."""
    args = launch.parse_args(["--interval-seconds", "10.5", "--iterations", "2"])
    assert args.interval_seconds == 10.5
    assert args.iterations == 2


def test_parse_args_rejects_nonpositive_interval_seconds():
    """parse_args rejects non-positive interval_seconds."""
    for value in ["0", "-1", "-3.5"]:
        with pytest.raises(SystemExit):
            launch.parse_args(["--interval-seconds", value])


def test_parse_args_rejects_nonpositive_iterations():
    """parse_args rejects non-positive iterations."""
    for value in ["0", "-1"]:
        with pytest.raises(SystemExit):
            launch.parse_args(["--iterations", value])


def test_build_worker_success(tmp_path: Path, monkeypatch):
    """build_worker assembles an XFeedWorker with monkeypatched env."""
    # Monkeypatch env vars so XClient.from_env() won't fail on missing creds.
    fake_env = {
        "X_BEARER_TOKEN": "fake_bearer",
        "X_API_KEY": "fake_key",
        "X_API_SECRET": "fake_secret",
        "X_ACCESS_TOKEN": "fake_access",
        "X_ACCESS_TOKEN_SECRET": "fake_access_secret",
    }
    for k, v in fake_env.items():
        monkeypatch.setenv(k, v)

    # Mock XClient.from_env to avoid any network or requests library instantiation.
    fake_x_client = MagicMock()
    with patch("soveryn.agents.x_feed.__main__.XClient") as mock_x_client_class:
        mock_x_client_class.from_env.return_value = fake_x_client

        args = launch.LauncherArgs(interval_seconds=300.0, iterations=None)
        worker = launch.build_worker(args)

    # Verify the result is an XFeedWorker instance.
    assert isinstance(worker, XFeedWorker)
    # Verify it received the faked x_client.
    assert worker.x_client is fake_x_client
    # Verify cfg is from default config.
    assert worker.cfg.own_handle == "Soveryn_AI"
    # Verify now_fn is time.time.
    assert worker.now_fn is time.time
    # Verify the store was instantiated (it's a CandidateStore).
    assert hasattr(worker, "store")
