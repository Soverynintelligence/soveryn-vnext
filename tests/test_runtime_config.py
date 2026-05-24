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


# ─── Service endpoints (spec §2, §3) ─────────────────────────────────────────

def test_parakeet_stt_service_endpoint_present():
    """Spec §3 + Jon's contract list: Parakeet STT is a Bucket A service on :8087."""
    parakeet = [e for e in runtime.SERVICE_ENDPOINTS if e.name == "parakeet_stt"]
    assert len(parakeet) == 1
    assert parakeet[0].port == 8087


def test_model_server_ports_are_exactly_8084_8085_8086_8089():
    """Spec §3 — llama-server endpoints only."""
    ports = {s.port for s in runtime.MODEL_SERVERS}
    assert ports == {8084, 8085, 8086, 8089}


def test_8089_is_cognition_not_aetheria_public():
    """Spec §3 — post-reset config.py drift would put aetheria_public on :8089. vNext refuses."""
    server_on_8089 = next(s for s in runtime.MODEL_SERVERS if s.port == 8089)
    assert server_on_8089.name == "cognition"
    assert "aetheria_public" not in server_on_8089.name
    assert "aetheria_public" not in server_on_8089.role


def test_all_ports_includes_parakeet():
    """all_ports() must surface every active-fleet port for preflight checks."""
    ports = runtime.all_ports()
    assert 8087 in ports
    assert ports == {8084, 8085, 8086, 8087, 8089}


def test_no_port_collisions_across_servers_services_app():
    """_validate() at import time should have rejected any collision. Sanity assert."""
    all_used = {s.port for s in runtime.MODEL_SERVERS}
    all_used |= {e.port for e in runtime.SERVICE_ENDPOINTS}
    all_used.add(runtime.APP_PORT)
    expected_count = len(runtime.MODEL_SERVERS) + len(runtime.SERVICE_ENDPOINTS) + 1
    assert len(all_used) == expected_count, "port collision somewhere"


# ─── Runtime services (process-level dependencies, spec §2, §8) ──────────────

def test_runtime_services_includes_all_required():
    """Spec §2, §8 Bucket A: these process-level dependencies must exist."""
    names = {r.name for r in runtime.RUNTIME_SERVICES}
    required = {"ares_daemon", "aetheria_stream", "heartbeat", "cognition", "dream_aetheria"}
    assert required.issubset(names), f"missing runtime services: {required - names}"


def test_runtime_service_kinds_are_constrained():
    """kind enum: process | thread | scheduled."""
    valid = {"process", "thread", "scheduled"}
    for r in runtime.RUNTIME_SERVICES:
        assert r.kind in valid, f"{r.name}: bad kind {r.kind!r}"


def test_runtime_service_launches_are_constrained():
    """launch enum: systemd | app_startup | user_launched."""
    valid = {"systemd", "app_startup", "user_launched"}
    for r in runtime.RUNTIME_SERVICES:
        assert r.launch in valid, f"{r.name}: bad launch {r.launch!r}"


def test_runtime_service_names_do_not_collide_with_agents_or_retired():
    service_names = {r.name for r in runtime.RUNTIME_SERVICES}
    assert not (service_names & set(runtime.ACTIVE_AGENTS))
    assert not (service_names & runtime.RETIRED)


def test_dream_aetheria_is_scheduled_via_systemd():
    """The nightly consolidation timer is a Bucket A scheduled service."""
    dream = next(r for r in runtime.RUNTIME_SERVICES if r.name == "dream_aetheria")
    assert dream.kind == "scheduled"
    assert dream.launch == "systemd"


def test_heartbeat_is_in_process_thread():
    """Heartbeat runs as a thread inside app.py, not a separate process."""
    hb = next(r for r in runtime.RUNTIME_SERVICES if r.name == "heartbeat")
    assert hb.kind == "thread"
    assert hb.launch == "app_startup"


def test_ares_daemon_is_a_process_not_an_agent():
    """Ares is a Bucket A daemon (process), not an active LLM agent."""
    ares = next(r for r in runtime.RUNTIME_SERVICES if r.name == "ares_daemon")
    assert ares.kind == "process"
    assert "ares_daemon" not in runtime.ACTIVE_AGENTS
    # daemon name "ares" should be in DAEMONS, not retired
    assert "ares" in runtime.DAEMONS
    assert "ares" not in runtime.RETIRED
