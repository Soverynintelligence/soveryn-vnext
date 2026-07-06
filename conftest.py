"""Root-level pytest configuration.

Adds ``--run-integration`` and ``--run-rig`` flags so tests marked
``@pytest.mark.integration`` (live services like the llama-server router)
and ``@pytest.mark.rig`` (real GPUs; fleet must be down) are skipped in
default unit-test runs — they need a specific environment and otherwise
fail spuriously in the standard gate.
"""
from __future__ import annotations


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run tests marked @pytest.mark.integration (hit live router etc.)",
    )
    parser.addoption(
        "--run-rig",
        action="store_true",
        default=False,
        help="Run tests marked @pytest.mark.rig (real GPUs; fleet must be down)",
    )


def pytest_collection_modifyitems(config, items):
    import pytest

    gates = []
    if not config.getoption("--run-integration"):
        gates.append(
            ("integration", pytest.mark.skip(reason="need --run-integration option to run"))
        )
    if not config.getoption("--run-rig"):
        gates.append(
            ("rig", pytest.mark.skip(reason="need --run-rig option to run (real GPUs, fleet must be down)"))
        )
    for item in items:
        for marker, skip in gates:
            if marker in item.keywords:
                item.add_marker(skip)
