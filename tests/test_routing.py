"""Tests for soveryn.inference.routing."""

from unittest.mock import patch
import pytest

from soveryn.inference.routing import RoutingError, route_for_agent


# ─── Happy path ──────────────────────────────────────────────────────────────

def test_aetheria_routes_to_aetheria_primary():
    server = route_for_agent("aetheria")
    assert server.name == "aetheria_primary"
    assert server.model_alias == "aetheria"


def test_vett_routes_to_shared_server():
    from soveryn.config.runtime import resolve_vett_brain, _VETT_BRAIN_PROFILES
    server = route_for_agent("vett")
    assert server.name == "vett_scotty_shared"
    # Spark :8001 is brain-swappable; alias follows ~/.soveryn/vett_brain.
    assert server.model_alias == _VETT_BRAIN_PROFILES[resolve_vett_brain()]["alias"]


def test_scotty_routes_to_shared_server():
    from soveryn.config.runtime import resolve_vett_brain, _VETT_BRAIN_PROFILES
    server = route_for_agent("scotty")
    assert server.name == "vett_scotty_shared"
    assert server.model_alias == _VETT_BRAIN_PROFILES[resolve_vett_brain()]["alias"]


def test_name_is_lowercased_and_stripped():
    assert route_for_agent("  Aetheria  ").name == "aetheria_primary"


# ─── Boundary 7 — unknown/retired must fail BEFORE any network I/O ───────────

@pytest.mark.parametrize("name", [
    "scout", "vision", "tinker", "forge",
    "ares_llm", "aetheria_public", "telegram", "chromadb",
])
def test_retired_agents_raise_routing_error(name):
    with pytest.raises(RoutingError, match="retired"):
        route_for_agent(name)


def test_unknown_agent_raises_routing_error():
    with pytest.raises(RoutingError, match="No route"):
        route_for_agent("fnord")


def test_retired_agent_lookup_does_not_touch_urllib():
    """Boundary 7: retired names must be rejected at the routing layer
    before any HTTP client can be reached."""
    with patch("urllib.request.urlopen") as mock_open:
        with pytest.raises(RoutingError):
            route_for_agent("scout")
        assert mock_open.call_count == 0


def test_unknown_agent_lookup_does_not_touch_urllib():
    with patch("urllib.request.urlopen") as mock_open:
        with pytest.raises(RoutingError):
            route_for_agent("fnord")
        assert mock_open.call_count == 0
