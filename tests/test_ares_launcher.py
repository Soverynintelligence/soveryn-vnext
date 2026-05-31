"""Tests for the Ares daemon launcher."""

from __future__ import annotations

import signal

import pytest

import soveryn.agents.ares.__main__ as launch


def test_parse_args_defaults_to_safe_mode():
    assert launch.parse_args([]) == launch.LauncherArgs()


def test_parse_args_no_dry_run_flag_disables_dry_run():
    args = launch.parse_args(["--no-dry-run"])
    assert args.dry_run is False
    assert args.interval_seconds == launch.DEFAULT_INTERVAL_SECONDS
    assert args.iterations is None


def test_parse_args_interval_seconds_override():
    args = launch.parse_args(["--interval-seconds", "12.5"])
    assert args == launch.LauncherArgs(interval_seconds=12.5)


def test_parse_args_rejects_nonpositive_interval_seconds():
    for value in ["0", "-1", "-3.5"]:
        with pytest.raises(SystemExit):
            launch.parse_args(["--interval-seconds", value])


def test_parse_args_iterations_override():
    args = launch.parse_args(["--iterations", "3"])
    assert args == launch.LauncherArgs(iterations=3)


def test_parse_args_rejects_nonpositive_iterations():
    for value in ["0", "-2"]:
        with pytest.raises(SystemExit):
            launch.parse_args(["--iterations", value])


def test_build_daemon_uses_dry_run_flag():
    assert launch.build_daemon(launch.LauncherArgs()).dry_run is True
    assert launch.build_daemon(launch.LauncherArgs(dry_run=False)).dry_run is False


def test_install_signal_handlers_wires_sigterm_and_sigint(monkeypatch):
    calls: list[tuple[int, object]] = []

    def fake_signal(signum, handler):
        calls.append((signum, handler))
        return None

    monkeypatch.setattr(launch.signal, "signal", fake_signal)
    shutdown = launch._ShutdownRequest()

    launch._install_signal_handlers(shutdown)

    assert calls == [
        (signal.SIGTERM, shutdown.request),
        (signal.SIGINT, shutdown.request),
    ]


def test_run_passes_control_knobs_and_stop_callback():
    captured: dict[str, object] = {}
    signal_state: dict[str, launch._ShutdownRequest] = {}

    class FakeDaemon:
        def run_forever(self, *, interval_seconds, iterations, stop_requested):
            captured["interval_seconds"] = interval_seconds
            captured["iterations"] = iterations
            captured["stop_requested_before"] = stop_requested()
            signal_state["shutdown"].request(signal.SIGTERM, None)
            captured["stop_requested_after"] = stop_requested()

    def daemon_factory(args):
        captured["args"] = args
        return FakeDaemon()

    def signal_installer(shutdown):
        signal_state["shutdown"] = shutdown

    rc = launch.run(
        launch.LauncherArgs(dry_run=False, interval_seconds=7.5, iterations=3),
        daemon_factory=daemon_factory,
        signal_installer=signal_installer,
    )

    assert rc == 0
    assert captured["args"] == launch.LauncherArgs(dry_run=False, interval_seconds=7.5, iterations=3)
    assert captured["interval_seconds"] == 7.5
    assert captured["iterations"] == 3
    assert captured["stop_requested_before"] is False
    assert captured["stop_requested_after"] is True


def test_main_parses_argv_and_returns_zero():
    captured: dict[str, object] = {}

    class FakeDaemon:
        def run_forever(self, *, interval_seconds, iterations, stop_requested):
            captured["interval_seconds"] = interval_seconds
            captured["iterations"] = iterations
            captured["stop_requested"] = stop_requested()

    def daemon_factory(args):
        captured["args"] = args
        daemon = FakeDaemon()
        daemon.dry_run = args.dry_run
        return daemon

    rc = launch.main(
        ["--no-dry-run", "--interval-seconds", "5", "--iterations", "2"],
        daemon_factory=daemon_factory,
        signal_installer=lambda shutdown: None,
    )

    assert rc == 0
    assert captured["args"] == launch.LauncherArgs(dry_run=False, interval_seconds=5.0, iterations=2)
    assert captured["interval_seconds"] == 5.0
    assert captured["iterations"] == 2
    assert captured["stop_requested"] is False
