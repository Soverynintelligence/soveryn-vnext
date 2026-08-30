"""Tests for soveryn.config.runtime invariants."""

import pytest
from soveryn.config import runtime


def test_active_agents_includes_crew_kernel_and_eve():
    """Crew + Kernel (build) + Eve (marketing). Kernel/Eve share :8091;
    Kernel writes stay Aider/HITL; Eve drafts via compose_post → Signal."""
    assert set(runtime.ACTIVE_AGENTS) == {
        "aetheria", "kernel", "eve",
    }
    assert "grok" not in runtime.ACTIVE_AGENTS
    assert "vett" not in runtime.ACTIVE_AGENTS
    assert "scotty" not in runtime.ACTIVE_AGENTS


def test_grok_is_not_a_house_agent():
    """Desktop Grok Bots — not a vNext AgentLoop / Messages contact."""
    assert "grok" not in runtime.AGENT_TO_SERVER
    assert all(s.name != "grok_build" for s in runtime.MODEL_SERVERS)


def test_messages_contacts_fleet_freeze():
    """Phone door is frontier few; Vett/Scotty/Grok parked as Messages peers."""
    assert runtime.MESSAGES_CONTACTS == (
        "aetheria", "kernel", "eve",
    )
    assert runtime.MESSAGES_PARKED == frozenset({"vett", "scotty"})
    assert runtime.DEFERRED_CHAT_AGENTS == frozenset({"kernel"})
    assert runtime.DEFERRED_CHAT_AGENTS <= set(runtime.MESSAGES_CONTACTS)
    assert runtime.COMMISSION_BLOCKED == frozenset({"vett", "scotty"})
    assert set(runtime.MESSAGES_CONTACTS).isdisjoint(runtime.MESSAGES_PARKED)
    assert set(runtime.MESSAGES_CONTACTS) <= set(runtime.ACTIVE_AGENTS)
    assert "vett" not in runtime.ACTIVE_AGENTS
    assert "scotty" not in runtime.ACTIVE_AGENTS
    assert "grok" not in runtime.ACTIVE_AGENTS


def test_commission_peers_are_eve_and_kernel_only():
    from soveryn.rooms.store import DEFAULT_PEER, PEERS

    assert PEERS == frozenset({"eve", "kernel"})
    assert DEFAULT_PEER == "eve"
    assert PEERS.isdisjoint(runtime.COMMISSION_BLOCKED)


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


def test_glm_kernel_window_is_32k():
    """2026-08-30: Kernel GLM TP=2 is 32k (was 16k; 16k 400'd ~17k prompts)."""
    kernel = next(s for s in runtime.MODEL_SERVERS if s.name == "kernel_build")
    if runtime.resolve_kernel_brain() == "glm":
        assert kernel.n_ctx == 32768
        assert kernel.host == "10.10.10.2" and kernel.port == 8001
    eve = next(s for s in runtime.MODEL_SERVERS if s.name == "eve_flash")
    assert eve.n_ctx == 65536
    assert eve.port == 8091
    assert eve.model_alias == "bench-flash"


def test_embeddings_url_resolves():
    # 2026-08-29 — Librarian back on helper Quadro loopback :8096 (Spark GLM).
    assert runtime.embeddings_url() == "http://127.0.0.1:8096"


# ─── Service endpoints (spec §2, §3) ─────────────────────────────────────────

def test_parakeet_stt_service_endpoint_present():
    """Spec §3 + Jon's contract list: Parakeet STT is a Bucket A service on :8087."""
    parakeet = [e for e in runtime.SERVICE_ENDPOINTS if e.name == "parakeet_stt"]
    assert len(parakeet) == 1
    assert parakeet[0].port == 8087


def test_aetheria_alone_on_8090_everyone_else_on_8091():
    """2026-07-14 — router SPLIT. llama.cpp/ggml initializes a CUDA context on
    every VISIBLE device — `--device` only restricts where layers are
    OFFLOADED, not what the process can see — so co-tenant models pinned via
    `--device CUDA2` were still leaking ~1.7GB onto Aetheria's Blackwell.
    CUDA_VISIBLE_DEVICES is the only real isolation, and router children
    inherit env from their router, so one router cannot serve both her and
    everyone else. Hence two routers:
        :8090  router-blackwell  -> aetheria ALONE (she does not share)
        :8091  router-quadro     -> vett-scotty, cognition, reflection
        :8096  embeddings        -> Librarian Nemotron-3-Embed-8B (own server)
    This test protects that split. If a future change "helpfully" merges the
    ports back to a single router, this must fail — that would silently
    reintroduce the Blackwell VRAM leak onto Aetheria's dedicated GPU.
    """
    aetheria = [s for s in runtime.MODEL_SERVERS if s.name == "aetheria_primary"]
    others = [s for s in runtime.MODEL_SERVERS if s.name != "aetheria_primary"]
    assert len(aetheria) == 1
    assert aetheria[0].port == 8090
    assert others, "expected at least one non-aetheria MODEL_SERVERS entry"
    # 2026-08-02: Vett + Scotty moved OFF the local routers entirely, to the
    # Spark, freeing 30 GB on a Quadro that was alerting at <1 GB free and
    # 82 C. That strengthens this invariant rather than weakening it — one
    # fewer tenant able to leak onto her card.
    # 2026-08-12: the Spark port moved :8000 -> :8001 when laguna-serve was
    # stopped and disabled and qwen-serve took over.
    # cognition on :8091; embeddings on its own :8096 Nemotron server.
    live_others = [s for s in others if not s.skip_preflight]
    assert {s.port for s in live_others} == {8001, 8091, 8096}
    # Local quadro slots stay on loopback; Spark tenants are remote.
    assert all(s.host == "127.0.0.1" for s in live_others if s.port in (8091, 8096))
    assert all(s.host != "127.0.0.1" for s in live_others if s.port == 8001)
    # And no non-aetheria entry may share Aetheria's port.
    assert all(s.port != 8090 for s in others)


def test_model_servers_have_distinct_logical_names():
    """Even though some share a port, MODEL_SERVERS remain distinct
    logical identities — that's the whole point of the (port, name) pair."""
    names = {s.name for s in runtime.MODEL_SERVERS}
    assert names == {
        "aetheria_primary",
        "vett_scotty_shared",
        "embeddings",
        "cognition",
        "kernel_build",
        "eve_flash",
    }


def test_each_model_server_has_router_alias_populated():
    """Under router mode, the chat/embeddings payload "model" field must match
    a preset alias registered in router-presets.ini. Verify each ModelServer
    carries the alias that router-presets.ini knows about.

    Vett/Scotty alias is brain-swappable (qwen36 | qwen38 | lightning) via
    ~/.soveryn/vett_brain — assert the active profile, not a fixed id.
    """
    brain = runtime.resolve_vett_brain()
    vett_alias = runtime._VETT_BRAIN_PROFILES[brain]["alias"]
    kbrain = runtime.resolve_kernel_brain()
    kernel_alias = runtime._KERNEL_BRAIN_PROFILES[kbrain]["alias"]
    expected = {
        "aetheria_primary": "aetheria",
        "vett_scotty_shared": vett_alias,
        "embeddings": "nemotron-embed-8b",
        "cognition": "cognition",
        "kernel_build": kernel_alias,
        "eve_flash": "bench-flash",
    }
    actual = {s.name: s.model_alias for s in runtime.MODEL_SERVERS}
    assert actual == expected


def test_kernel_brain_defaults_to_flash(tmp_path, monkeypatch):
    monkeypatch.delenv("SOVERYN_KERNEL_BRAIN", raising=False)
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", tmp_path / "missing")
    assert runtime.resolve_kernel_brain() == "flash"


def test_kernel_brain_file_and_env(tmp_path, monkeypatch):
    path = tmp_path / "kernel_brain"
    path.write_text("qwen38\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", path)
    monkeypatch.delenv("SOVERYN_KERNEL_BRAIN", raising=False)
    assert runtime.resolve_kernel_brain() == "qwen38"
    monkeypatch.setenv("SOVERYN_KERNEL_BRAIN", "flash")
    assert runtime.resolve_kernel_brain() == "flash"


def test_eve_stays_on_flash_when_kernel_on_qwen38(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_KERNEL_BRAIN", "qwen38")
    # Re-import factory through resolve — MODEL_SERVERS is built at import.
    # Spot-check profile wiring instead of rebinding the frozen tuple.
    assert runtime._KERNEL_BRAIN_PROFILES["qwen38"]["alias"] == "qwen38-27b"
    assert runtime._KERNEL_BRAIN_PROFILES["flash"]["alias"] == "bench-flash"
    assert runtime.AGENT_TO_SERVER["eve"] == "eve_flash"
    assert runtime.AGENT_TO_SERVER["kernel"] == "kernel_build"


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
    Router SPLIT + Librarian: the model-server side is now THREE ports —
    :8090 (Blackwell, aetheria alone), :8091 (Quadro, vett-scotty/cognition),
    and :8096 (Librarian embeddings) — because Aetheria's GPU must never be shared."""
    ports = runtime.all_ports()
    assert 8087 in ports
    # 8001 = Spark vLLM (qwen-serve), added 2026-08-02 on :8000 and moved to
    # :8001 on 2026-08-12 when laguna-serve was stopped and disabled.
    assert ports == {8001, 8087, 8090, 8091, 8096}


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
    # "cognition" was renamed "cognition_cycle" on 2026-07-31 to disambiguate
    # the DAEMON from soveryn-cognition.service, which is the MODEL SERVER
    # on :8089. Both existed; only the name collided.
    required = {"ares_daemon", "heartbeat", "cognition_cycle", "dream_aetheria"}
    assert required.issubset(names), f"missing runtime services: {required - names}"
    assert "aetheria_stream" not in names


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


def test_dream_aetheria_is_a_long_running_systemd_service():
    """Dream runs continuously under soveryn-dream.service, not on a timer.

    Corrected 2026-07-31. This previously asserted kind="scheduled", describing
    a nightly timer that does not exist: `systemctl --user list-timers` shows no
    dream timer, and PID 1153351 is owned by soveryn-dream.service with
    Type=simple. Quiet-hours gating happens inside the daemon
    (SOVERYN_DREAM_QUIET_HOURS), not in systemd.

    Third test found on 2026-07-31 to be enforcing a false declaration — see
    test_heartbeat_is_a_systemd_process. Four of the registry's six pre-existing
    entries were wrong, and tests held three of them in place.
    """
    dream = next(r for r in runtime.RUNTIME_SERVICES if r.name == "dream_aetheria")
    assert dream.kind == "process"
    assert dream.launch == "systemd"


def test_heartbeat_is_a_systemd_process():
    """Heartbeat runs as its own systemd user unit, not a thread inside app.py.

    Corrected 2026-07-31. This test previously asserted kind="thread" /
    launch="app_startup" and so *enforced* a declaration that was never true:
    the heartbeat has always run as `python -m soveryn.agents.heartbeat` under
    soveryn-heartbeat.service. Correcting the registry would have failed CI,
    which is the most likely reason the wrong declaration survived.

    A test that locks in a false fact is worse than no test — it converts a
    stale document into an enforced one.
    """
    hb = next(r for r in runtime.RUNTIME_SERVICES if r.name == "heartbeat")
    assert hb.kind == "process"
    assert hb.launch == "systemd"


def test_ares_daemon_is_a_process_not_an_agent():
    """Ares is a Bucket A daemon (process), not an active LLM agent."""
    ares = next(r for r in runtime.RUNTIME_SERVICES if r.name == "ares_daemon")
    assert ares.kind == "process"
    assert "ares_daemon" not in runtime.ACTIVE_AGENTS
    # daemon name "ares" should be in DAEMONS, not retired
    assert "ares" in runtime.DAEMONS
    assert "ares" not in runtime.RETIRED


def test_vett_scotty_shared_does_not_support_multi_system_on_stock_qwen():
    """INVERTED 2026-08-12, and the reason matters more than the value.

    From 2026-06-12 this asserted True: the router child loaded
    froggeric/Qwen-Fixed-Chat-Templates v20 via `chat-template-file`, which
    natively honoured messages[1:] role=system, so `prepare_wire_messages`
    was a pass-through.

    That patched template went away with the router child. Vett and Scotty now
    reach STOCK Qwen3.6 served by vLLM on the Spark, which returns
    `400 System message must be at the beginning` for any system message after
    position 0. True was only ever a property of the patched template, never of
    the model — so the flag follows the server, and the adapter is load-bearing
    again."""
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
