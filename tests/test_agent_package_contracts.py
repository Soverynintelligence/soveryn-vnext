"""Tests for explicit agent package contracts."""

import pytest

from soveryn.agents.ares.daemon import (
    AresDaemonNotPortedError,
    AresDaemonSurface,
    AresFinding,
)
from soveryn.agents.registry import AgentRegistry, AgentRegistryError
from soveryn.agents.scotty.repair_surface import (
    RepairRequest,
    ScottyRepairNotPortedError,
    ScottyRepairSurface,
)
from soveryn.agents.vett.research_surface import (
    ResearchRequest,
    VettResearchNotPortedError,
    VettResearchSurface,
)
from soveryn.config.runtime import ACTIVE_AGENTS, DAEMONS, RETIRED


def test_agent_package_contracts_import_and_name_surfaces():
    assert AresDaemonSurface.agent_name == "ares"
    assert AresDaemonSurface.uses_llm is False
    assert VettResearchSurface.agent_name == "vett"
    assert ScottyRepairSurface.agent_name == "scotty"


def test_contract_dataclasses_are_instantiable():
    finding = AresFinding("filesystem", "low", {"path": "/tmp"})
    research = ResearchRequest("find source", constraints={"fresh": True})
    repair = RepairRequest("restart_service", "A", {"service": "demo"})

    assert finding.severity == "low"
    assert research.constraints == {"fresh": True}
    assert repair.tier == "A"


def test_contract_surfaces_are_declared_not_ported():
    with pytest.raises(AresDaemonNotPortedError):
        AresDaemonSurface().scan_once()
    with pytest.raises(VettResearchNotPortedError):
        VettResearchSurface().run(ResearchRequest("query"))
    with pytest.raises(ScottyRepairNotPortedError):
        ScottyRepairSurface().execute(RepairRequest("recipe", "A", {}))


def test_explicit_cast_is_aetheria_ares_vett_scotty_only():
    assert set(ACTIVE_AGENTS) == {"aetheria", "vett", "scotty"}
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
