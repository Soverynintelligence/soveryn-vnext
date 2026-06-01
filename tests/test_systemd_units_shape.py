"""Shape tests for systemd user-unit files."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEMD_DIR = REPO_ROOT / "systemd"


def _load_unit(name: str) -> ConfigParser:
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    with (SYSTEMD_DIR / name).open(encoding="utf-8") as fh:
        parser.read_file(fh)
    return parser


def test_router_unit_has_required_sections():
    unit = _load_unit("soveryn-router.service")
    assert unit.has_section("Unit")
    assert unit.has_section("Service")
    assert unit.has_section("Install")
    assert unit.get("Unit", "Description") == "SOVERYN llama-server router (:8090)"


def test_router_unit_runs_llama_server_router_on_port_8090():
    unit = _load_unit("soveryn-router.service")
    execstart = unit.get("Service", "ExecStart")
    assert execstart.startswith("/home/jon-deoliveira/llama.cpp/build/bin/llama-server")
    assert "--models-preset /home/jon-deoliveira/soveryn_complete/router-presets.ini" in execstart
    assert "--models-max 4" in execstart
    assert "--host 127.0.0.1" in execstart
    assert "--port 8090" in execstart


def test_router_unit_is_user_scoped_and_restarts_on_failure():
    unit = _load_unit("soveryn-router.service")
    assert unit.get("Service", "User") == "jon-deoliveira"
    assert unit.get("Service", "Restart") == "on-failure"
    assert unit.get("Service", "TimeoutStartSec") == "180"
    assert unit.get("Service", "Type") == "simple"


def test_router_unit_installs_under_soveryn_target():
    unit = _load_unit("soveryn-router.service")
    assert unit.get("Install", "WantedBy") == "soveryn.target"


def test_vnext_unit_has_router_dependency_and_execstartpre_waits_on_props():
    unit = _load_unit("soveryn-vnext.service")
    assert unit.get("Unit", "After") == "soveryn-router.service"
    assert unit.get("Unit", "Requires") == "soveryn-router.service"
    pre = unit.get("Service", "ExecStartPre")
    assert "python -m soveryn.platform.supervisor.readiness" in pre
    assert "http://127.0.0.1:8090/props" in pre
    assert "--name router" in pre
    assert "--max-wait 180" in pre


def test_vnext_unit_runs_flask_app_on_5001_with_locked_env_port():
    unit = _load_unit("soveryn-vnext.service")
    assert unit.get("Service", "Environment") == "SOVERYN_APP_PORT=5001"
    assert unit.get("Service", "ExecStart").endswith("-m soveryn.app")
    assert "python" in unit.get("Service", "ExecStart")
    assert unit.get("Service", "WorkingDirectory") == "/home/jon-deoliveira/soveryn_vnext"


def test_vnext_unit_restarts_on_failure_and_times_out_for_cold_start():
    unit = _load_unit("soveryn-vnext.service")
    assert unit.get("Service", "Restart") == "on-failure"
    assert unit.get("Service", "RestartSec") == "5"
    assert unit.get("Service", "TimeoutStartSec") == "180"
    assert unit.get("Service", "Type") == "simple"


def test_vnext_unit_installs_under_soveryn_target():
    unit = _load_unit("soveryn-vnext.service")
    assert unit.get("Install", "WantedBy") == "soveryn.target"


def test_ares_unit_waits_for_vnext_health_and_runs_without_restart():
    unit = _load_unit("soveryn-ares.service")
    assert unit.get("Unit", "After") == "soveryn-vnext.service"
    assert unit.get("Unit", "Requires") == "soveryn-vnext.service"
    pre = unit.get("Service", "ExecStartPre")
    assert "python -m soveryn.platform.supervisor.readiness" in pre
    assert "http://127.0.0.1:5001/health" in pre
    assert "--name vnext" in pre
    assert unit.get("Service", "ExecStart").endswith("-m soveryn.agents.ares")
    assert unit.get("Service", "Restart") == "no"


def test_ares_unit_is_user_scoped_and_timebounded():
    unit = _load_unit("soveryn-ares.service")
    assert unit.get("Service", "User") == "jon-deoliveira"
    assert unit.get("Service", "WorkingDirectory") == "/home/jon-deoliveira/soveryn_vnext"
    assert unit.get("Service", "TimeoutStartSec") == "180"
    assert unit.get("Service", "Type") == "simple"


def test_ares_unit_installs_under_soveryn_target():
    unit = _load_unit("soveryn-ares.service")
    assert unit.get("Install", "WantedBy") == "soveryn.target"


def test_soveryn_target_wants_all_three_services():
    unit = _load_unit("soveryn.target")
    wants = unit.get("Unit", "Wants")
    assert "soveryn-router.service" in wants
    assert "soveryn-vnext.service" in wants
    assert "soveryn-ares.service" in wants


def test_soveryn_target_installs_under_default_target():
    unit = _load_unit("soveryn.target")
    assert unit.get("Install", "WantedBy") == "default.target"
