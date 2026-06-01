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
