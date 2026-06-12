"""Smoke tests for the Vett harness port (phase 1).

These tests assert the SOVERYN harness package directory is importable.
Integration-seam tests (against the vendored harness, the lattice, and
the live router) land in Task 12.
"""
from __future__ import annotations
import importlib
import uuid


def test_package_importable():
    """The SOVERYN harness package directory is importable.

    This is a structural floor — catches syntax errors in __init__.py
    and confirms the package path resolves. It does NOT exercise any
    integration seam; those are tested in Task 12.
    """
    mod = importlib.import_module("soveryn.agents.vett.harness")
    assert mod is not None


def test_vendored_harness_importable():
    """All vendored upstream modules import cleanly from their new home."""
    expected = [
        "soveryn.agents.vett.harness.vendor.agent",
        "soveryn.agents.vett.harness.vendor.config",
        "soveryn.agents.vett.harness.vendor.prompts",
        "soveryn.agents.vett.harness.vendor.rerank",
        "soveryn.agents.vett.harness.vendor.tasks",
        "soveryn.agents.vett.harness.vendor.tools",
        "soveryn.agents.vett.harness.vendor.trajectory",
        "soveryn.agents.vett.harness.vendor.ultra_core",
        "soveryn.agents.vett.harness.vendor.utils",
    ]
    for module_path in expected:
        importlib.import_module(module_path)


def test_vendored_trajectory_class_present():
    """Trajectory is the Pydantic class the harness uses to carry state."""
    from soveryn.agents.vett.harness.vendor.trajectory import Trajectory
    t = Trajectory(actions_and_observations=[], id=uuid.uuid4())
    assert t.num_turns == 0


def test_vendor_compat_aliases_harness():
    """After install_vendor_compat(), `import harness` resolves to our vendored package."""
    from soveryn.agents.vett.harness import _vendor_compat
    _vendor_compat.install_vendor_compat()
    import harness as aliased  # noqa: E402  — alias is the whole point
    from soveryn.agents.vett.harness import vendor
    assert aliased is vendor, "harness alias did not resolve to vendor package"


def test_vendor_compat_tinker_stub_imports_succeed_but_fail_on_use():
    """tinker stub allows imports; raises clear RuntimeError when actually used."""
    from soveryn.agents.vett.harness import _vendor_compat
    _vendor_compat.install_vendor_compat()
    import tinker  # noqa: E402
    SamplingClient = tinker.SamplingClient  # accessor must not raise
    try:
        SamplingClient()
    except RuntimeError as e:
        assert "SOVERYN" in str(e) and "SoverynVettInferenceModel" in str(e), \
            f"stub error should direct caller to SoverynVettInferenceModel; got: {e}"
    else:
        raise AssertionError("Tinker stub did not raise when instantiated")


import subprocess
import sys
import tempfile
from pathlib import Path
import json

import pytest


@pytest.mark.integration
def test_end_to_end_smoke_task_against_live_services():
    """The CLI runs the 'smoke' task end-to-end and produces a valid trajectory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "trajectory.json"
        result = subprocess.run(
            [sys.executable, "-m", "soveryn.agents.vett.harness.run_eval",
             "--task", "smoke", "--output", str(out_path),
             "--max-turns", "3"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert "actions_and_observations" in data
        assert "[telemetry]" in result.stderr
