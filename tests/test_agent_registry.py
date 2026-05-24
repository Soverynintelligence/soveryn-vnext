"""Tests for soveryn.agents.registry."""

import pytest
from soveryn.agents.registry import AgentRegistry, AgentRegistryError


def make_dummy_agent(name):
    """Lightweight stand-in for an AgentLoop while we have no real implementation."""
    return {"name": name, "kind": "dummy"}


def test_register_active_agent_succeeds():
    reg = AgentRegistry()
    reg.register("aetheria", make_dummy_agent("aetheria"))
    assert reg.has("aetheria")
    assert reg.get("aetheria")["kind"] == "dummy"


def test_register_all_three_active_agents():
    reg = AgentRegistry()
    for name in ("aetheria", "vett", "scotty"):
        reg.register(name, make_dummy_agent(name))
    assert reg.names() == ("aetheria", "scotty", "vett")
    assert len(reg) == 3


@pytest.mark.parametrize("name", [
    "scout", "vision", "tinker", "forge",
    "ares_llm", "aetheria_public", "telegram", "chromadb",
])
def test_register_retired_agent_raises(name):
    reg = AgentRegistry()
    with pytest.raises(AgentRegistryError, match="retired"):
        reg.register(name, make_dummy_agent(name))


def test_register_unknown_agent_raises():
    reg = AgentRegistry()
    with pytest.raises(AgentRegistryError, match="not in ACTIVE_AGENTS"):
        reg.register("fnord", make_dummy_agent("fnord"))


def test_get_retired_agent_raises():
    reg = AgentRegistry()
    with pytest.raises(AgentRegistryError, match="retired"):
        reg.get("scout")


def test_register_same_instance_twice_is_idempotent():
    reg = AgentRegistry()
    agent = make_dummy_agent("aetheria")
    reg.register("aetheria", agent)
    reg.register("aetheria", agent)  # same instance
    assert len(reg) == 1


def test_register_conflicting_instance_raises():
    reg = AgentRegistry()
    reg.register("aetheria", make_dummy_agent("aetheria"))
    with pytest.raises(AgentRegistryError, match="already registered"):
        reg.register("aetheria", make_dummy_agent("aetheria"))  # different dict


def test_name_is_lowercased_and_stripped():
    reg = AgentRegistry()
    reg.register("  Aetheria  ", make_dummy_agent("aetheria"))
    assert reg.has("aetheria")
    assert reg.has("AETHERIA")  # canonical form is lowercase
