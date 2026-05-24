"""Tests for soveryn.config.runtime invariants."""

import pytest
from soveryn.config import runtime


def test_active_agents_is_exactly_three():
    """Spec §1, §8 Bucket A: Aetheria, Vett, Scotty. No more, no less."""
    assert set(runtime.ACTIVE_AGENTS) == {"aetheria", "vett", "scotty"}


def test_retired_includes_known_retired_agents():
    """Spec §10 Bucket C: these names must be blocked."""
    must_be_retired = {
        "scout", "vision", "tinker", "forge",
        "ares_llm", "aetheria_public",
        "telegram", "chromadb",
    }
    assert must_be_retired.issubset(runtime.RETIRED)


def test_active_and_retired_do_not_overlap():
    assert not (set(runtime.ACTIVE_AGENTS) & runtime.RETIRED)


def test_every_active_agent_has_a_server_route():
    unrouted = set(runtime.ACTIVE_AGENTS) - set(runtime.AGENT_TO_SERVER)
    assert not unrouted, f"Active agents without routing: {unrouted}"


def test_routes_target_real_servers():
    server_names = {s.name for s in runtime.MODEL_SERVERS}
    for agent, server in runtime.AGENT_TO_SERVER.items():
        assert server in server_names, f"{agent} → unknown server {server!r}"


def test_no_retired_name_appears_as_a_server_or_route_target():
    for s in runtime.MODEL_SERVERS:
        assert s.name not in runtime.RETIRED
    for agent in runtime.AGENT_TO_SERVER:
        assert agent not in runtime.RETIRED


def test_app_port_is_5001_during_side_by_side():
    """Production is :5000; vNext must not collide."""
    assert runtime.APP_PORT == 5001


def test_embeddings_url_resolves():
    assert runtime.embeddings_url() == "http://127.0.0.1:8086"
