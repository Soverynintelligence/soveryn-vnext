"""Tests for soveryn.app.__main__ — CLI launcher.

Never starts a real server. Inject a fake runner; assert what the
launcher RESOLVED and what it would have called.
"""

import pytest
from pathlib import Path

from soveryn.app.__main__ import (
    DEFAULT_HOST,
    LauncherError,
    PRODUCTION_PORT,
    _build_startup_line,
    _resolve_launch_config,
    main,
)
from soveryn.config.loader import EnvConfig
from soveryn.config.runtime import ACTIVE_AGENTS


def _env(app_port=5001, lattice_db="/tmp/lattice_vnext.db", conv_db="/tmp/conv_vnext.db",
          souls_dir="/tmp/souls", pinned_memory_path="/tmp/pinned_memory.md",
          recall_lattice_db="/tmp/recall_lattice.db",
          salience_db="/tmp/salience_vnext.db",
          data_root="/tmp/test-data",
          cognition_instance_url="http://127.0.0.1:8089",
          skills_dir="/tmp/skills"):
    return EnvConfig(
        app_port=app_port,
        model_root=Path("/tmp/models"),
        health_timeout_seconds=2.0,
        cognition_instance_url=cognition_instance_url,
        lattice_db=Path(lattice_db),
        conversations_db=Path(conv_db),
        souls_dir=Path(souls_dir),
        skills_dir=Path(skills_dir),
        pinned_memory_path=Path(pinned_memory_path),
        recall_lattice_db=Path(recall_lattice_db),
        data_root=Path(data_root),
        salience_db=Path(salience_db),
        cross_surface_enabled=True,
        cross_surface_window_hours=6,
        cross_surface_token_budget=1500,
        cross_surface_per_session_cap=400,
        elevenlabs_api_key=None,
        elevenlabs_voice_id_aetheria=None,
        voice_root=Path("/tmp/test-voice"),
    )


# ─── _resolve_launch_config ──────────────────────────────────────────────────

def test_resolve_defaults_to_localhost_and_env_port():
    host, port = _resolve_launch_config(_env(app_port=5001), None, None)
    assert host == DEFAULT_HOST == "127.0.0.1"
    assert port == 5001


def test_resolve_host_override_wins():
    host, _ = _resolve_launch_config(_env(), "10.0.0.5", None)
    assert host == "10.0.0.5"


def test_resolve_port_override_wins():
    _, port = _resolve_launch_config(_env(app_port=5001), None, 7000)
    assert port == 7000


def test_resolve_refuses_production_port_default():
    """Even if env.app_port were misconfigured to 5000, launcher refuses."""
    with pytest.raises(LauncherError, match="5000"):
        _resolve_launch_config(_env(app_port=5000), None, None)


def test_resolve_refuses_production_port_override():
    with pytest.raises(LauncherError, match="5000"):
        _resolve_launch_config(_env(), None, 5000)


def test_resolve_allows_5001_explicitly():
    _, port = _resolve_launch_config(_env(app_port=5001), None, 5001)
    assert port == 5001


# ─── _build_startup_line ─────────────────────────────────────────────────────

def test_startup_line_contains_host_port_agents_dbs():
    line = _build_startup_line(
        "127.0.0.1", 5001, _env(lattice_db="/x/lat.db", conv_db="/x/conv.db"),
        ["aetheria", "vett", "scotty"],
    )
    assert "http://127.0.0.1:5001" in line
    assert "aetheria" in line and "vett" in line and "scotty" in line
    assert "/x/lat.db" in line
    assert "/x/conv.db" in line
    assert "\n" not in line  # single line


def test_startup_line_sorts_agents_for_determinism():
    line = _build_startup_line(
        "127.0.0.1", 5001, _env(), ["vett", "aetheria", "scotty"],
    )
    # alphabetical
    assert "[aetheria,scotty,vett]" in line


# ─── main() with injected fake runner (never binds) ──────────────────────────

class _RecordingRunner:
    def __init__(self):
        self.called = False
        self.args = None
    def __call__(self, app, *, host, port):
        self.called = True
        self.args = {"app": app, "host": host, "port": port}


def _fake_app_factory(*, env=None, conv_store=None, agent_loops=None):
    """Stand-in factory that returns an object shaped like Flask app for the
    launcher's `app.extensions['soveryn']['agent_loops']` access."""
    class _A:
        extensions = {"soveryn": {"agent_loops": {n: object() for n in ACTIVE_AGENTS}}}
    return _A()


def test_main_calls_runner_with_resolved_host_port(capsys):
    runner = _RecordingRunner()
    rc = main(argv=[], app_factory=_fake_app_factory, runner=runner)
    assert rc == 0
    assert runner.called is True
    assert runner.args["host"] == DEFAULT_HOST
    # Port comes from EnvConfig default (5001 unless env overrides — in test env it should be 5001)
    assert runner.args["port"] != PRODUCTION_PORT
    # Startup line printed
    captured = capsys.readouterr()
    assert "[soveryn] vNext serving on" in captured.out
    assert "agents=" in captured.out


def test_main_host_flag_overrides(capsys):
    runner = _RecordingRunner()
    main(argv=["--host", "10.1.1.1"], app_factory=_fake_app_factory, runner=runner)
    assert runner.args["host"] == "10.1.1.1"


def test_main_port_flag_overrides(capsys):
    runner = _RecordingRunner()
    main(argv=["--port", "7777"], app_factory=_fake_app_factory, runner=runner)
    assert runner.args["port"] == 7777


def test_main_refuses_port_5000(capsys):
    runner = _RecordingRunner()
    with pytest.raises(LauncherError, match="5000"):
        main(argv=["--port", "5000"], app_factory=_fake_app_factory, runner=runner)
    assert runner.called is False  # never reached the runner


def test_main_never_calls_real_app_run(monkeypatch, capsys):
    """If the launcher accidentally called Flask's app.run, this test would
    hang or error. The injected runner replaces it; we never touch the real one."""
    real_run_calls = {"n": 0}
    def explode(*a, **kw):
        real_run_calls["n"] += 1
        raise AssertionError("real Flask app.run was called from tests")
    # Patch Flask.app.run on the real Flask class as defense in depth.
    from flask import Flask
    monkeypatch.setattr(Flask, "run", explode)
    runner = _RecordingRunner()
    main(argv=[], app_factory=_fake_app_factory, runner=runner)
    assert real_run_calls["n"] == 0


def test_main_returns_zero_on_success(capsys):
    runner = _RecordingRunner()
    assert main(argv=[], app_factory=_fake_app_factory, runner=runner) == 0
