"""SOVERYN vNext — runtime configuration.

Single source of truth for agent identity, model paths, ports, GPU assignment.
Everything else (registry, routing, startup, UI) reads from here. There is no
other place agent names or model paths should appear.

Derived from docs/CURRENT_TRUTH_2026-05-23.md § 1, 3, 4, 8, 10.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Agent identity
# ─────────────────────────────────────────────────────────────────────────────

#: Agents with a live `AgentLoop` and chat surface (spec §1, §8 Bucket A)
ACTIVE_AGENTS: tuple[str, ...] = ("aetheria", "vett", "scotty")

#: Background processes that are NOT agents but are part of the active fleet
#: (spec §2, §8 Bucket A). These have no `AgentLoop` and don't respond to /chat.
DAEMONS: frozenset[str] = frozenset({"ares"})

#: Names that MUST NOT appear anywhere in vNext code paths (spec §10 Bucket C).
#: The registry rejects these at registration time. Tests enforce that no
#: vNext file in soveryn/ references them as agent identities.
RETIRED: frozenset[str] = frozenset({
    "scout",
    "vision",
    "tinker",
    "forge",            # never existed, spec §10
    "ares_llm",         # the old in-process Ares agent (daemon stays)
    "aetheria_public",  # spec §10 — never went live in production
    "telegram",         # channel name retired in favor of signal
    "chromadb",         # memory backend retired in favor of lattice
})

# ─────────────────────────────────────────────────────────────────────────────
# Model + server map (spec §1, §3)
# ─────────────────────────────────────────────────────────────────────────────

MODEL_ROOT = Path("/mnt/soveryn_models/GGUF")


@dataclass(frozen=True)
class ModelServer:
    """A single llama-server endpoint.

    2026-07-14 — router SPLIT. There are now TWO routers, because llama.cpp
    initializes a CUDA context on every VISIBLE device (`--device` restricts
    where layers are OFFLOADED, not what is visible), so co-tenant models were
    leaking ~1.7GB onto Aetheria's Blackwell. Each router is pinned with
    CUDA_VISIBLE_DEVICES to only the cards it may touch:
        :8090  router-blackwell  -> aetheria ALONE (she does not share)
        :8091  router-quadro     -> vett-scotty, embeddings, cognition, reflection
    A router that cannot SEE a card cannot allocate on it.
    `name` remains the logical preset identity inside vNext;
    `model_alias` is the router-facing identifier sent in the OpenAI `model`
    field. The router's preset .ini (soveryn_vnext/runtime/router-presets.ini)
    has both the alias and the model basename registered, so both resolve.
    """
    name: str                       # logical identity, e.g. "aetheria_primary"
    port: int                       # 127.0.0.1:<port>  — 8090 = Blackwell router (aetheria only), 8091 = Quadro router
    model_path: Path                # GGUF file
    mmproj_path: Path | None = None
    role: str = ""                  # human-readable: "Aetheria primary inference", etc.
    #: Whether this server's chat template accepts multiple system messages.
    #: Default True (modern permissive case). Set False for base Qwen3.5/3.6
    #: 27B templates which reject any second system message — AgentLoop then
    #: concatenates the soul into the persona content as a single system msg.
    supports_multi_system_messages: bool = True
    #: Router-facing model identifier. This goes into the "model" field of
    #: /v1/chat/completions and /v1/embeddings request bodies. Must match a
    #: preset alias (section name or registered basename) in router-presets.ini.
    model_alias: str = ""


#: Endpoints vNext will route to. Mirrors spec §1/§3 exactly.
MODEL_SERVERS: tuple[ModelServer, ...] = (
    ModelServer(
        name="aetheria_primary",
        port=8090,
        # Gemma 4 31B + its mmproj. Swapped off Qwen3.6-35B-A3B on
        # 2026-06-01 — see project_soveryn_aetheria_gemma4.md. The router
        # preset at ~/soveryn_vnext/runtime/router-presets.ini [aetheria] is
        # what actually loads the model; this metadata only needs to
        # agree with the preset.
        model_path=MODEL_ROOT / "google_gemma-4-31B-it-Q8_0.gguf",
        mmproj_path=MODEL_ROOT / "mmproj-google_gemma-4-31B-it-bf16.gguf",
        role="Aetheria primary (Gemma 4 31B + mmproj on Blackwell)",
        # Kept False for safety — the prelude fold is a pass-through when
        # the template supports multi-system, so leaving it on costs
        # nothing structurally. Flip to True only after a controlled probe
        # confirms Gemma 4's template honors messages[1:] role=system.
        supports_multi_system_messages=False,
        model_alias="aetheria",
    ),
    ModelServer(
        name="vett_scotty_shared",
        port=8091,
        model_path=MODEL_ROOT / "Qwen_Qwen3.6-27B-Q8_0.gguf",
        mmproj_path=MODEL_ROOT / "mmproj-Qwen_Qwen3.6-27B-bf16.gguf",
        role="Vett + Scotty shared Qwen3.6-27B (Quadro GPU 0)",
        # Flipped to True 2026-06-12: vett-scotty router child now uses
        # froggeric/Qwen-Fixed-Chat-Templates v20 (configured via
        # `chat-template-file = ...` in router-presets.ini [vett-scotty]),
        # which natively honors messages[1:] role=system. Sandbox-verified
        # + live-verified through router :8090 (multi-system probe returned
        # "ALL_SURVIVED" exact). The transport adapter `prepare_wire_messages`
        # becomes a pass-through for this server.
        supports_multi_system_messages=True,
        model_alias="vett-scotty",
    ),
    ModelServer(
        name="embeddings",
        # 2026-07-17 Librarian: repointed off the nomic router (:8091) to the
        # standalone Nemotron-3-Embed-8B server (:8096, sentence-transformers in
        # the isolated nemo-embed env). 4096-dim; lattice fully re-embedded.
        # model_path below is cosmetic now — the :8096 server is self-contained.
        port=8096,
        model_path=MODEL_ROOT / "nomic-embed-text-v1.5.Q8_0.gguf",
        role="Embedding backend: Nemotron-3-Embed-8B on :8096, used by Lattice",
        model_alias="embeddings",
    ),
    ModelServer(
        name="cognition",
        port=8091,
        model_path=MODEL_ROOT / "gemma-4-E4B-it-Q8_0.gguf",
        role="Cognition layer — dream consolidation, background dispatch worker",
        model_alias="cognition",
    ),
)

#: Per-agent routing: agent name → MODEL_SERVERS.name
AGENT_TO_SERVER: dict[str, str] = {
    "aetheria": "aetheria_primary",
    "vett":     "vett_scotty_shared",
    "scotty":   "vett_scotty_shared",
}

# ─────────────────────────────────────────────────────────────────────────────
# Non-llama service endpoints (spec §2, §3, §8 Bucket A)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ServiceEndpoint:
    """A non-llama-server service endpoint (STT, etc.) the active fleet depends on.

    Distinct from `ModelServer` because there's no GGUF model — these are
    independent Python services with their own runtime.
    """
    name: str               # logical identity, e.g. "parakeet_stt"
    port: int               # 127.0.0.1:<port>
    role: str = ""          # human-readable purpose


#: Active-fleet services that are NOT llama-servers but ARE Bucket A. vNext's
#: preflight must verify these are reachable before declaring boot healthy.
SERVICE_ENDPOINTS: tuple[ServiceEndpoint, ...] = (
    ServiceEndpoint(
        name="parakeet_stt",
        port=8087,
        role="Speech-to-text (Parakeet, conda env `parakeet`, systemd parakeet.service)",
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# Runtime services (process-level dependencies — spec §2, §8 Bucket A)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RuntimeService:
    """A process-level runtime dependency that's part of the active fleet.

    NOT a network endpoint (those are `ModelServer` / `ServiceEndpoint`),
    NOT an agent (those are `ACTIVE_AGENTS`). These are background
    processes, in-process threads, or scheduled jobs that must be
    alive/wired for the system to function. vNext preflight checks each
    of these has either a running process or a scheduled job, depending
    on `kind`.
    """
    name: str
    kind: str       # "process" | "thread" | "scheduled"
    launch: str     # "systemd" | "app_startup" | "user_launched"
    role: str = ""


#: Active-fleet runtime services. Spec §2, §8 Bucket A.
RUNTIME_SERVICES: tuple[RuntimeService, ...] = (
    RuntimeService(
        name="ares_daemon",
        kind="process",
        launch="user_launched",
        role="Security daemon — scans + posts findings to inboxes (no LLM)",
    ),
    RuntimeService(
        name="heartbeat",
        kind="thread",
        launch="app_startup",
        role="AetheriaAutonomy autonomous cycle (thread inside app.py)",
    ),
    RuntimeService(
        name="cognition",
        kind="thread",
        launch="app_startup",
        role="AetheriaCognition thread inside app.py — POSTs to cognition :8089",
    ),
    RuntimeService(
        name="dream_aetheria",
        kind="scheduled",
        launch="systemd",
        role="Nightly memory consolidation @ 03:00 (soveryn-dream-aetheria.timer)",
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Application surface
# ─────────────────────────────────────────────────────────────────────────────

#: Flask app port for vNext during side-by-side validation. Production is :5000.
APP_PORT: int = 5001

#: Dedicated cognition llama-server instance (Gemma 4 E4B on its own port).
#: Background-only — the foreground chat path must never import or depend on it.
#: Override via SOVERYN_COGNITION_INSTANCE_URL env var (handled in loader.py).
COGNITION_INSTANCE_URL: str = "http://127.0.0.1:8091"


#: Embedding endpoint URL derived from MODEL_SERVERS (convenience).
def embeddings_url() -> str:
    server = next(s for s in MODEL_SERVERS if s.name == "embeddings")
    return f"http://127.0.0.1:{server.port}"


# ─────────────────────────────────────────────────────────────────────────────
# Sanity invariants — checked at import time
# ─────────────────────────────────────────────────────────────────────────────

def _validate() -> None:
    """Run at import. Fail loud if the config is internally inconsistent."""
    # No agent name appears in RETIRED
    overlap = set(ACTIVE_AGENTS) & RETIRED
    if overlap:
        raise RuntimeError(f"ACTIVE_AGENTS overlaps RETIRED: {overlap}")
    # No daemon name appears in ACTIVE_AGENTS or RETIRED
    daemon_overlap = (DAEMONS & set(ACTIVE_AGENTS)) | (DAEMONS & RETIRED)
    if daemon_overlap:
        raise RuntimeError(f"DAEMONS overlaps active/retired: {daemon_overlap}")
    # Every agent routes to a real server
    server_names = {s.name for s in MODEL_SERVERS}
    for agent, server in AGENT_TO_SERVER.items():
        if agent not in ACTIVE_AGENTS:
            raise RuntimeError(f"AGENT_TO_SERVER references non-active agent {agent!r}")
        if server not in server_names:
            raise RuntimeError(f"Agent {agent!r} routes to unknown server {server!r}")
    # Every active agent has a route
    unrouted = set(ACTIVE_AGENTS) - set(AGENT_TO_SERVER)
    if unrouted:
        raise RuntimeError(f"Active agents without server routing: {unrouted}")
    # Port-collision invariant under router mode (Phase 7, 2026-05-26):
    # MODEL_SERVERS are split across TWO router ports (8090 Blackwell / 8091 Quadro) because one
    # llama-server router process proxies all four logical servers via the
    # "model" field. The collision check therefore validates uniqueness by
    # (port, name) for MODEL_SERVERS — duplicates on port alone are allowed
    # — while still preventing MODEL_SERVERS ports from colliding with
    # SERVICE_ENDPOINTS or APP_PORT (those are independent processes that
    # cannot share a port with the router or each other).
    ms_keys = [(s.port, s.name) for s in MODEL_SERVERS]
    if len(ms_keys) != len(set(ms_keys)):
        raise RuntimeError(f"MODEL_SERVERS has duplicate (port, name): {ms_keys}")
    ms_names = [s.name for s in MODEL_SERVERS]
    if len(ms_names) != len(set(ms_names)):
        raise RuntimeError(f"MODEL_SERVERS has duplicate names: {ms_names}")
    ms_ports = {s.port for s in MODEL_SERVERS}
    se_names = [e.name for e in SERVICE_ENDPOINTS]
    if len(se_names) != len(set(se_names)):
        raise RuntimeError(f"SERVICE_ENDPOINTS has duplicate names: {se_names}")
    for e in SERVICE_ENDPOINTS:
        if e.port in ms_ports:
            raise RuntimeError(
                f"Port {e.port} collision: SERVICE_ENDPOINTS:{e.name} vs MODEL_SERVERS"
            )
    se_ports = {e.port for e in SERVICE_ENDPOINTS}
    if len(se_ports) != len(SERVICE_ENDPOINTS):
        raise RuntimeError(f"SERVICE_ENDPOINTS has duplicate ports: {[e.port for e in SERVICE_ENDPOINTS]}")
    if APP_PORT in ms_ports:
        raise RuntimeError(f"APP_PORT {APP_PORT} collides with MODEL_SERVERS")
    if APP_PORT in se_ports:
        raise RuntimeError(f"APP_PORT {APP_PORT} collides with SERVICE_ENDPOINTS")
    # RuntimeService.kind / launch are constrained vocabularies
    valid_kinds = {"process", "thread", "scheduled"}
    valid_launches = {"systemd", "app_startup", "user_launched"}
    for r in RUNTIME_SERVICES:
        if r.kind not in valid_kinds:
            raise RuntimeError(f"RuntimeService {r.name!r}: invalid kind {r.kind!r}")
        if r.launch not in valid_launches:
            raise RuntimeError(f"RuntimeService {r.name!r}: invalid launch {r.launch!r}")
    # RuntimeService names must not collide with agent names or each other
    service_names = [r.name for r in RUNTIME_SERVICES]
    if len(service_names) != len(set(service_names)):
        raise RuntimeError(f"RUNTIME_SERVICES has duplicate names: {service_names}")
    name_overlap = set(service_names) & (set(ACTIVE_AGENTS) | RETIRED)
    if name_overlap:
        raise RuntimeError(f"RuntimeService names overlap agents/retired: {name_overlap}")


def all_ports() -> frozenset[int]:
    """Every port the active fleet should be listening on (excluding APP_PORT)."""
    return frozenset(
        {s.port for s in MODEL_SERVERS} | {e.port for e in SERVICE_ENDPOINTS}
    )


_validate()
