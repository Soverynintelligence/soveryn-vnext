"""Tests for explicit agent package contracts."""

import pytest

from soveryn.agents.ares.daemon import (
    AresDaemonSurface,
    AresFinding,
)
from soveryn.agents.registry import AgentRegistry, AgentRegistryError
from soveryn.config.runtime import ACTIVE_AGENTS, DAEMONS, RETIRED


def test_agent_package_contracts_import_and_name_surfaces():
    assert AresDaemonSurface.agent_name == "ares"
    assert AresDaemonSurface.uses_llm is False


def test_contract_dataclasses_are_instantiable():
    finding = AresFinding("filesystem", "low", {"path": "/tmp"})

    assert finding.severity == "low"


def test_ares_daemon_surface_now_scans_without_llm(tmp_path):
    from soveryn.agents.ares.findings import FindingTracker

    surface = AresDaemonSurface(
        collectors=[lambda: []],
        tracker=FindingTracker(tmp_path / "ares_state.json"),
        sinks=None,
    )

    assert surface.scan_once() == ()
    assert surface.uses_llm is False


def test_explicit_cast_matches_active_roster_and_ares_daemon():
    """Chat roster is ACTIVE_AGENTS; Ares stays a daemon, never a chat agent."""
    assert set(ACTIVE_AGENTS) == {
        "aetheria", "forge", "eve",
    }
    assert DAEMONS == frozenset({"ares"})
    assert "ares" not in ACTIVE_AGENTS


def test_no_retired_agent_can_be_registered():
    registry = AgentRegistry()

    for name in RETIRED:
        with pytest.raises(AgentRegistryError):
            registry.register(name, object())


def test_active_chat_agents_still_register_but_daemon_does_not():
    registry = AgentRegistry()
    for name in ACTIVE_AGENTS:
        registry.register(name, object())

    assert set(registry.names()) == set(ACTIVE_AGENTS)
    with pytest.raises(AgentRegistryError, match="not in ACTIVE_AGENTS"):
        registry.register("ares", AresDaemonSurface())
