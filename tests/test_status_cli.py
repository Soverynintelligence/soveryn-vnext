"""Tests for the soveryn.status CLI.

Reuses preflight via injection; no real HTTP, no real systemctl.
"""

from __future__ import annotations

from pathlib import Path

from soveryn.status import main


def test_status_cli_prints_preflight_report_and_returns_zero_when_ok(capsys):
    from soveryn.app.preflight import PreflightReport
    from soveryn.config.loader import load_env_config
    from soveryn.inference.health import HealthResult

    def fake_run_preflight():
        return PreflightReport(env=load_env_config(env={}), results=(
            HealthResult("aetheria_primary", "model_server", "ok", 1.0, "HTTP 200"),
        ))

    rc = main(argv=[], run_preflight=fake_run_preflight)
    out = capsys.readouterr().out
    assert rc == 0
    assert "aetheria_primary" in out
    assert "PREFLIGHT OK" in out


def test_status_cli_returns_nonzero_when_any_check_fails(capsys):
    from soveryn.app.preflight import PreflightReport
    from soveryn.config.loader import load_env_config
    from soveryn.inference.health import HealthResult

    def fake_run_preflight():
        return PreflightReport(env=load_env_config(env={}), results=(
            HealthResult("ares_daemon", "runtime_service", "fail", 1.0, "no matching process"),
        ))

    rc = main(argv=[], run_preflight=fake_run_preflight)
    out = capsys.readouterr().out
    assert rc == 1
    assert "ares_daemon" in out
    assert "PREFLIGHT FAILED" in out


def test_install_script_is_executable_and_has_help():
    """Verify the install script exists, is owner-executable, and exposes the
    expected operator modes without running real systemctl."""
    import stat

    script = Path(__file__).parent.parent / "scripts" / "install_systemd_units.sh"
    assert script.is_file()
    assert script.stat().st_mode & stat.S_IXUSR
    content = script.read_text(encoding="utf-8")
    assert "--install" in content
    assert "--uninstall" in content
    assert "--dry-run" in content
