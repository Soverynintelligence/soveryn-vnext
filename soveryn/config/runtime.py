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
    """A single llama-server endpoint."""
    name: str                       # logical identity, e.g. "aetheria_primary"
    port: int                       # 127.0.0.1:<port>
    model_path: Path                # GGUF file
    mmproj_path: Path | None = None
    role: str = ""                  # human-readable: "Aetheria primary inference", etc.


#: Endpoints vNext will route to. Mirrors spec §1/§3 exactly.
MODEL_SERVERS: tuple[ModelServer, ...] = (
    ModelServer(
        name="aetheria_primary",
        port=8085,
        model_path=MODEL_ROOT / "Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf",
        mmproj_path=MODEL_ROOT / "Qwen3.6-35B-A3B-UD-Q8_K_XL.mmproj-BF16.gguf",
        role="Aetheria primary (Blackwell 90% + Quadro spillover 10%)",
    ),
    ModelServer(
        name="vett_scotty_shared",
        port=8084,
        model_path=MODEL_ROOT / "Qwen3.5-27B-Q8_0.gguf",
        mmproj_path=MODEL_ROOT / "mmproj-Qwen3.5-27B-F16.gguf",
        role="Vett + Scotty shared 27B (Quadro GPU 0)",
    ),
    ModelServer(
        name="embeddings",
        port=8086,
        model_path=MODEL_ROOT / "nomic-embed-text-v1.5.Q8_0.gguf",
        role="Single embedding backend (nomic-embed), used by Lattice",
    ),
    ModelServer(
        name="cognition",
        port=8089,
        model_path=MODEL_ROOT / "gemma-4-E4B-it-Q8_0.gguf",
        role="Cognition layer — dream consolidation, background dispatch worker",
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
        name="aetheria_stream",
        kind="process",
        launch="user_launched",
        role="Aetheria streaming / proprioception surface (separate process)",
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
    # No port collision across MODEL_SERVERS, SERVICE_ENDPOINTS, APP_PORT
    seen_ports: dict[int, str] = {}
    for s in MODEL_SERVERS:
        if s.port in seen_ports:
            raise RuntimeError(f"Port {s.port} collision: {seen_ports[s.port]} vs MODEL_SERVERS:{s.name}")
        seen_ports[s.port] = f"MODEL_SERVERS:{s.name}"
    for e in SERVICE_ENDPOINTS:
        if e.port in seen_ports:
            raise RuntimeError(f"Port {e.port} collision: {seen_ports[e.port]} vs SERVICE_ENDPOINTS:{e.name}")
        seen_ports[e.port] = f"SERVICE_ENDPOINTS:{e.name}"
    if APP_PORT in seen_ports:
        raise RuntimeError(f"APP_PORT {APP_PORT} collides with {seen_ports[APP_PORT]}")
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
