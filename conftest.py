"""Root-level pytest configuration.

Adds the ``--run-integration`` flag so tests marked
``@pytest.mark.integration`` (which hit live services like the
llama-server router) are skipped in default unit-test runs.
"""
from __future__ import annotations


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run tests marked @pytest.mark.integration (hit live router etc.)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    import pytest

    skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
