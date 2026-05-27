"""Tests for the Phase 1 platform package skeleton."""

from importlib import import_module


def test_platform_package_imports():
    modules = [
        "soveryn.platform",
        "soveryn.platform.lattice",
        "soveryn.platform.tools",
        "soveryn.platform.inference",
        "soveryn.platform.bus",
        "soveryn.platform.supervisor",
        "soveryn.platform.telemetry",
        "soveryn.platform.repair",
    ]

    for module_name in modules:
        module = import_module(module_name)
        assert module.__doc__

