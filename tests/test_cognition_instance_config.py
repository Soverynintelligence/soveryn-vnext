"""Shape tests for the soveryn-cognition-instance.service unit file.

This unit is hardware-gated (needs a free Quadro after DGX Spark arrives).
Tests validate the unit file shape without starting the service.

Mirror of tests/test_systemd_units_shape.py patterns.
"""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SYSTEMD_DIR = REPO_ROOT / "systemd"

UNIT_NAME = "soveryn-cognition-instance.service"


def _load_unit(name: str) -> ConfigParser:
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    with (SYSTEMD_DIR / name).open(encoding="utf-8") as fh:
        parser.read_file(fh)
    return parser


def test_cognition_instance_unit_exists():
    """The unit file must be present in the repo's systemd/ directory."""
    assert (SYSTEMD_DIR / UNIT_NAME).exists(), (
        f"Unit file not found: {SYSTEMD_DIR / UNIT_NAME}"
    )


def test_cognition_instance_unit_has_required_sections():
    unit = _load_unit(UNIT_NAME)
    assert unit.has_section("Unit")
    assert unit.has_section("Service")
    assert unit.has_section("Install")


def test_cognition_instance_unit_description_mentions_8091():
    unit = _load_unit(UNIT_NAME)
    desc = unit.get("Unit", "Description")
    assert "8091" in desc, f"Description should mention port 8091, got: {desc!r}"


def test_cognition_instance_unit_targets_port_8091():
    unit = _load_unit(UNIT_NAME)
    execstart = unit.get("Service", "ExecStart")
    assert "--port 8091" in execstart, (
        f"ExecStart must contain '--port 8091', got: {execstart!r}"
    )


def test_cognition_instance_unit_uses_full_gemma4_31b_model():
    unit = _load_unit(UNIT_NAME)
    execstart = unit.get("Service", "ExecStart")
    assert "google_gemma-4-31B-it-Q8_0.gguf" in execstart, (
        f"ExecStart must reference full Gemma 4 31B model GGUF"
    )
    assert "mmproj-google_gemma-4-31B-it-bf16.gguf" in execstart, (
        f"ExecStart must reference Gemma 4 31B mmproj"
    )


def test_cognition_instance_unit_sets_alias_aetheria_cognition():
    unit = _load_unit(UNIT_NAME)
    execstart = unit.get("Service", "ExecStart")
    assert "--alias aetheria-cognition" in execstart, (
        f"ExecStart must contain '--alias aetheria-cognition'"
    )


def test_cognition_instance_unit_has_device_flag():
    """Unit must pin to a CUDA device. Exact id confirmed at hardware bring-up."""
    unit = _load_unit(UNIT_NAME)
    execstart = unit.get("Service", "ExecStart")
    assert "--device CUDA" in execstart, (
        f"ExecStart must contain a '--device CUDA<n>' flag, got: {execstart!r}"
    )


def test_cognition_instance_unit_carries_cuda_compat_env():
    """HEAD llama.cpp build needs the cuda-compat LD_LIBRARY_PATH shim."""
    unit = _load_unit(UNIT_NAME)
    env = unit.get("Service", "Environment")
    assert "cuda-compat" in env, (
        f"Service Environment must include cuda-compat LD_LIBRARY_PATH line"
    )
    assert "LD_LIBRARY_PATH" in env, (
        f"Service Environment must set LD_LIBRARY_PATH"
    )


def test_cognition_instance_unit_installs_under_soveryn_target():
    unit = _load_unit(UNIT_NAME)
    assert unit.get("Install", "WantedBy") == "soveryn.target"


def test_cognition_instance_unit_restarts_on_failure():
    unit = _load_unit(UNIT_NAME)
    assert unit.get("Service", "Restart") == "on-failure"
    assert unit.get("Service", "Type") == "simple"


def test_cognition_instance_unit_hosts_on_loopback():
    unit = _load_unit(UNIT_NAME)
    execstart = unit.get("Service", "ExecStart")
    assert "--host 127.0.0.1" in execstart, (
        f"ExecStart must bind to loopback 127.0.0.1"
    )
