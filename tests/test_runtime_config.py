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
    # Phase 7 (2026-05-26) — router cutover: all MODEL_SERVERS share :8090.
    assert runtime.embeddings_url() == "http://127.0.0.1:8090"


# ─── Service endpoints (spec §2, §3) ─────────────────────────────────────────

def test_parakeet_stt_service_endpoint_present():
    """Spec §3 + Jon's contract list: Parakeet STT is a Bucket A service on :8087."""
    parakeet = [e for e in runtime.SERVICE_ENDPOINTS if e.name == "parakeet_stt"]
    assert len(parakeet) == 1
    assert parakeet[0].port == 8087


def test_model_servers_all_route_through_router_port_8090():
    """Phase 7 router cutover: one llama-server router on :8090 fronts every
    logical preset via per-model dispatch in the request body's "model" field."""
    ports = {s.port for s in runtime.MODEL_SERVERS}
    assert ports == {8090}


def test_model_servers_have_distinct_logical_names():
    """Even though they share a port, the four MODEL_SERVERS remain distinct
    logical identities — that's the whole point of the (port, name) pair."""
    names = {s.name for s in runtime.MODEL_SERVERS}
    assert names == {"aetheria_primary", "vett_scotty_shared", "embeddings", "cognition"}


def test_each_model_server_has_router_alias_populated():
    """Under router mode, the chat/embeddings payload "model" field must match
    a preset alias registered in router-presets.ini. Verify each ModelServer
    carries the alias that router-presets.ini knows about."""
    expected = {
        "aetheria_primary": "aetheria",
        "vett_scotty_shared": "vett-scotty",
        "embeddings": "embeddings",
        "cognition": "cognition",
    }
    actual = {s.name: s.model_alias for s in runtime.MODEL_SERVERS}
    assert actual == expected


def test_cognition_is_cognition_not_aetheria_public():
    """Spec §3 — post-reset config.py drift would put aetheria_public somewhere
    Aetheria-confusable. vNext refuses. (Pre-Phase-7 this was bound to :8089;
    under router mode the test instead checks the cognition logical entry.)"""
    cognition = next(s for s in runtime.MODEL_SERVERS if s.name == "cognition")
    assert cognition.model_alias == "cognition"
    assert "aetheria_public" not in cognition.name
    assert "aetheria_public" not in cognition.role


def test_all_ports_includes_parakeet():
    """all_ports() must surface every active-fleet port for preflight checks.
    Under router mode the model-server side collapses to a single port."""
    ports = runtime.all_ports()
    assert 8087 in ports
    assert ports == {8087, 8090}


def test_model_servers_can_share_port_but_not_with_service_endpoints():
    """_validate() at import time enforces the router-mode invariant: MODEL_SERVERS
    may share ports with each other (router architecture) but must not collide
    with SERVICE_ENDPOINTS or APP_PORT."""
    ms_ports = {s.port for s in runtime.MODEL_SERVERS}
    se_ports = {e.port for e in runtime.SERVICE_ENDPOINTS}
    assert ms_ports.isdisjoint(se_ports), "MODEL_SERVERS port collides with SERVICE_ENDPOINTS"
    assert runtime.APP_PORT not in ms_ports, "APP_PORT collides with MODEL_SERVERS"
    assert runtime.APP_PORT not in se_ports, "APP_PORT collides with SERVICE_ENDPOINTS"
    # Names within MODEL_SERVERS must still be unique (port + name pair uniqueness)
    ms_names = [s.name for s in runtime.MODEL_SERVERS]
    assert len(ms_names) == len(set(ms_names)), "MODEL_SERVERS has duplicate names"


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


def test_vett_scotty_shared_marked_as_single_system_only():
    """Base Qwen3.6-27B chat template rejects multiple system messages;
    vett_scotty_shared MUST be flagged so AgentLoop concatenates the soul."""
    from soveryn.config.runtime import MODEL_SERVERS
    vs = next(s for s in MODEL_SERVERS if s.name == "vett_scotty_shared")
    assert vs.supports_multi_system_messages is False


def test_aetheria_primary_does_not_support_multi_system_qwen36_template():
    """Aetheria's Qwen3.6 35B jinja chat template silently drops messages[1:]
    of role=system (controlled probe 2026-05-30 — single 2,642-char system
    message yielded 577 prompt_tokens; four system messages totaling 730 chars
    yielded only 87 prompt_tokens, consistent with only the first reaching the
    model). Transport adapter `prepare_wire_messages` folds at wire.

    See project_soveryn_qwen36_multisystem_drop and
    project_soveryn_three_tracks_workaround_capability_agency.
    """
    from soveryn.config.runtime import MODEL_SERVERS
    a = next(s for s in MODEL_SERVERS if s.name == "aetheria_primary")
    assert a.supports_multi_system_messages is False
