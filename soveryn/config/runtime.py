"""SOVERYN vNext — runtime configuration.

Single source of truth for agent identity, model paths, ports, GPU assignment.
Everything else (registry, routing, startup, UI) reads from here. There is no
other place agent names or model paths should appear.

Derived from docs/CURRENT_TRUTH_2026-05-23.md § 1, 3, 4, 8, 10.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Agent identity
# ─────────────────────────────────────────────────────────────────────────────

#: Agents with a live `AgentLoop` and chat surface (spec §1, §8 Bucket A).
#: Kernel is the house build brain (bench-flash on :8091) — chat + memory + read;
#: file writes stay via Aider / HITL, not free exec tools.
ACTIVE_AGENTS: tuple[str, ...] = (
    "aetheria", "vett", "scotty", "kernel", "eve", "grok",
)

#: Messages contact list (phone door). Subset of ACTIVE_AGENTS + overnight
#: inboxes are layered in the UI. Fleet freeze 2026-08-27: frontier few —
#: one card / one frontier mind. Vett + Scotty stay in ACTIVE_AGENTS for
#: engine-room commissions/automations but are **not** Messages contacts.
MESSAGES_CONTACTS: tuple[str, ...] = (
    "aetheria",  # soul / face — Blackwell alone
    "kernel",    # local build lane
    "eve",       # ship posts (Canva / Signal)
    "grok",      # cloud coding peer (headless Build CLI — no local VRAM)
)

#: Parked as Messages peers (still may exist as ACTIVE_AGENTS).
MESSAGES_PARKED: frozenset[str] = frozenset({"vett", "scotty"})

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
    port: int                       # <host>:<port> — 8090 = Blackwell router (aetheria only), 8091 = Quadro router
    model_path: Path                # GGUF file
    #: Host serving this model. Defaults to loopback because every backend was
    #: local until 2026-08-02, when Vett + Scotty moved to the Spark over the
    #: CX-7 link to free 30 GB on a Quadro that was alerting at <1 GB free.
    #: Callers must use `base_url`, never a hardcoded 127.0.0.1.
    host: str = "127.0.0.1"
    #: Extra chat_template_kwargs sent with every request to this server.
    #: Needed for Laguna on vLLM: with NO kwargs the template pre-fills the
    #: opening <think>, the model emits only the closing tag, and
    #: --reasoning-parser poolside_v1 (looking for a matched pair) leaves a
    #: literal "</think>" at the head of message.content. Passing the kwarg
    #: explicitly — either value — makes the parser work. Verified 2026-08-02
    #: against the live server; not DFlash, not the vLLM version, not a missing
    #: parser flag, all of which were ruled out first.
    chat_template_kwargs: dict | None = None
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
    #: When True, preflight does not probe this endpoint (external backends
    #: such as Grok Build CLI that inject custom chat_fn and never hit llama).
    skip_preflight: bool = False

    @property
    def base_url(self) -> str:
        """http://<host>:<port> — the single place a backend URL is formed."""
        return f"http://{self.host}:{self.port}"


# Vett/Scotty Spark "hard brains" — one live model on :8001 at a time.
# Side-by-side as named peers (not dual-load). Does NOT touch Aetheria / Kernel.
# Switch:  scripts/switch_vett_brain.sh qwen36|qwen38|lightning
#          or CC Ops / Hard-brain strip → POST /api/ops/brain
# Precedence: SOVERYN_VETT_BRAIN env > ~/.soveryn/vett_brain > qwen36
# Aliases must match Spark serve-*.sh --served-model-name.
_VETT_BRAIN_PROFILES: dict[str, dict] = {
    "qwen36": {
        "alias": "qwen36-35b",
        "house_name": "Qwen 3.6",
        "blurb": "MoE 35B-A3B · MTP · prior hard brain",
        "role": "Vett + Scotty shared Qwen3.6-35B-A3B NVFP4 (Spark, vLLM, MTP)",
        "path": "Qwen3.6-35B-A3B-NVFP4",
    },
    "qwen38": {
        "alias": "qwen38-27b",
        "house_name": "Qwen 3.8",
        "blurb": "Dense 27B · local-class peak · NVFP4 on Spark",
        "role": "Vett + Scotty shared Qwen3.8-27B NVFP4 dense (Spark, vLLM) — "
                "named peer to Lightning; not Aetheria soul, not Kernel",
        "path": "Qwen3.8-27B-NVFP4",
    },
    "lightning": {
        "alias": "lightning-30b",
        "house_name": "Lightning",
        "blurb": "Nemotron 3.5 · MoE ~3B active · daily default",
        "role": "Vett + Scotty shared Nemotron 3.5 Lightning 30B-A3B NVFP4 (Spark, vLLM)",
        "path": "Nemotron-3.5-Lightning-30B-A3B-NVFP4",
    },
}
_VETT_BRAIN_FILE = Path.home() / ".soveryn" / "vett_brain"


def resolve_vett_brain() -> str:
    """Return brain key: qwen36 | qwen38 | lightning."""
    env = (os.environ.get("SOVERYN_VETT_BRAIN") or "").strip().lower()
    if env in _VETT_BRAIN_PROFILES:
        return env
    try:
        key = _VETT_BRAIN_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        key = ""
    if key in _VETT_BRAIN_PROFILES:
        return key
    return "qwen36"


def _vett_scotty_server() -> ModelServer:
    """Build the Spark backend ModelServer for the currently selected brain."""
    key = resolve_vett_brain()
    prof = _VETT_BRAIN_PROFILES[key]
    return ModelServer(
        name="vett_scotty_shared",
        host="10.10.10.2",  # Spark, over the CX-7 link
        port=8001,  # vLLM via qwen-serve.service -> serve-active.sh
        model_path=MODEL_ROOT / prof["path"],  # cosmetic; weights live on Spark
        mmproj_path=None,
        role=prof["role"],
        # Stock Qwen/Nemotron on vLLM reject multi system messages (HTTP 400).
        supports_multi_system_messages=False,
        model_alias=prof["alias"],
        # Thinking off: overnight harness showed enable_thinking=True raised
        # false-deny of the agent's own action on some backends.
        chat_template_kwargs={"enable_thinking": False},
    )


# Kernel build brain — Flash on Quadros (default) or Qwen3.8 on Spark :8001.
# Switch:  scripts/switch_kernel_brain.sh flash|qwen38
# Precedence: SOVERYN_KERNEL_BRAIN env > ~/.soveryn/kernel_brain > flash
# qwen38 uses Spark's served alias — Spark must already be on qwen38
# (switch_vett_brain.sh qwen38) unless you pass --take-spark.
_KERNEL_BRAIN_PROFILES: dict[str, dict] = {
    "flash": {
        "alias": "bench-flash",
        "house_name": "Flash",
        "blurb": "DeepSeek V4 Flash · Quadros :8091 · daily build default",
        "host": "127.0.0.1",
        "port": 8091,
        "path": (
            "DeepSeek-V4-Flash-0731/UD-Q4_K_XL/"
            "DeepSeek-V4-Flash-0731-UD-Q4_K_XL-00001-of-00005.gguf"
        ),
        "role": "Kernel — house build brain (DeepSeek V4 Flash on Quadros :8091)",
    },
    "qwen38": {
        "alias": "qwen38-27b",
        "house_name": "Qwen 3.8",
        "blurb": "Dense 27B NVFP4 · Spark :8001 · heavier build turns",
        "host": "10.10.10.2",
        "port": 8001,
        "path": "Qwen3.8-27B-NVFP4",
        "role": (
            "Kernel — house build brain (Qwen3.8-27B NVFP4 on Spark :8001). "
            "Shares the Spark slot with Vett/Scotty when that brain is loaded."
        ),
    },
}
_KERNEL_BRAIN_FILE = Path.home() / ".soveryn" / "kernel_brain"


def resolve_kernel_brain() -> str:
    """Return Kernel brain key: flash | qwen38."""
    env = (os.environ.get("SOVERYN_KERNEL_BRAIN") or "").strip().lower()
    if env in _KERNEL_BRAIN_PROFILES:
        return env
    try:
        key = _KERNEL_BRAIN_FILE.read_text(encoding="utf-8").strip().lower()
    except OSError:
        key = ""
    if key in _KERNEL_BRAIN_PROFILES:
        return key
    return "flash"


def _kernel_server() -> ModelServer:
    """Kernel build backend for the currently selected brain."""
    key = resolve_kernel_brain()
    prof = _KERNEL_BRAIN_PROFILES[key]
    return ModelServer(
        name="kernel_build",
        host=str(prof["host"]),
        port=int(prof["port"]),
        model_path=MODEL_ROOT / str(prof["path"]),
        mmproj_path=None,
        role=str(prof["role"]),
        supports_multi_system_messages=False,
        model_alias=str(prof["alias"]),
        chat_template_kwargs={"enable_thinking": False},
    )


def _eve_flash_server() -> ModelServer:
    """Eve always on Quadros Flash — does not follow Kernel to Spark."""
    flash = _KERNEL_BRAIN_PROFILES["flash"]
    return ModelServer(
        name="eve_flash",
        host=str(flash["host"]),
        port=int(flash["port"]),
        model_path=MODEL_ROOT / str(flash["path"]),
        mmproj_path=None,
        role="Eve — presence/marketing on Quadros Flash (pinned; not Kernel-switched)",
        supports_multi_system_messages=False,
        model_alias=str(flash["alias"]),
        chat_template_kwargs={"enable_thinking": False},
    )


#: Endpoints vNext will route to. Mirrors spec §1/§3 exactly.
MODEL_SERVERS: tuple[ModelServer, ...] = (
    ModelServer(
        name="aetheria_primary",
        port=8090,
        # CUTOVER 2026-08-17: Qwen3.8-27B UD-Q6_K_XL (was Gemma 4 31B).
        # Live weights come from router-presets-blackwell.ini [aetheria];
        # this metadata must agree. Gemma rollback: model=aetheria-gemma.
        model_path=MODEL_ROOT / "Qwen3.8-27B-UD-Q6_K_XL.gguf",
        mmproj_path=MODEL_ROOT / "mmproj-Qwen3.8-27B-BF16.gguf",
        role="Aetheria primary (Qwen3.8-27B + mmproj on Blackwell)",
        # Kept False for safety — prelude fold is pass-through when multi-system
        # works. Stock Qwen on some backends rejects multi system (vett path).
        supports_multi_system_messages=False,
        model_alias="aetheria",
        # Thinking off for soul/desk feel (Qwen overthink was why we left before).
        chat_template_kwargs={"enable_thinking": False},
    ),
    _vett_scotty_server(),
    ModelServer(
        name="embeddings",
        # 2026-08-17: Lattice librarian moved to Spark (fabric). Same Nemotron-Embed-8B
        # weights — NOT Lightning chat. Lightning stays hard-brain on :8001; embed is a
        # separate process on :8096 so vectors stay in the 4096-d space the Lattice
        # already uses. Frees ~15G Quadro on the tower for Kernel.
        host="10.10.10.2",
        port=8096,
        model_path=MODEL_ROOT / "Nemotron-3-Embed-8B-BF16",
        role="Lattice librarian: Nemotron-3-Embed-8B on Spark :8096 (fabric)",
        model_alias="nemotron-embed-8b",
    ),
    ModelServer(
        name="cognition",
        port=8091,
        model_path=MODEL_ROOT / "gemma-4-E4B-it-Q8_0.gguf",
        role="Cognition layer — dream consolidation, background dispatch worker",
        model_alias="cognition",
    ),
    _kernel_server(),
    _eve_flash_server(),
    # Grok Build — Messages coding peer. Not a llama-server; AgentLoop injects
    # grok_build_client chat_fn/stream_fn. Port is bookkeeping only.
    ModelServer(
        name="grok_build",
        port=5099,
        host="127.0.0.1",
        model_path=MODEL_ROOT / ".grok_build_external",
        role="Grok Build CLI — Messages coding peer (headless grok)",
        model_alias="grok-build",
        skip_preflight=True,
    ),
)

#: Per-agent routing: agent name → MODEL_SERVERS.name
AGENT_TO_SERVER: dict[str, str] = {
    "aetheria": "aetheria_primary",
    "vett":     "vett_scotty_shared",
    "scotty":   "vett_scotty_shared",
    "kernel":   "kernel_build",
    # Eve stays on Quadros Flash even when Kernel rides Spark Qwen3.8.
    "eve":      "eve_flash",
    "grok":     "grok_build",
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
        launch="systemd",
        role="Security daemon — scans + posts findings to inboxes (no LLM)",
    ),
    RuntimeService(
        name="heartbeat",
        kind="process",
        launch="systemd",
        role="AetheriaAutonomy autonomous cycle — soveryn-heartbeat.service "
             "(python -m soveryn.agents.heartbeat). Corrected 2026-07-31: this "
             "was declared a thread inside app.py and never was one.",
    ),
    RuntimeService(
        name="delegation-worker",
        kind="thread",
        launch="app_startup",
        role="Delegation executor — picks up dispatched tasks, runs Scotty in a "
             "worktree under bwrap, applies the acceptance gate "
             "(startup.py, thread). Added to the registry 2026-07-31: it was "
             "running and undeclared.",
    ),
    RuntimeService(
        name="messenger-delivery-worker",
        kind="thread",
        launch="app_startup",
        role="Messenger outbound delivery (startup.py, thread). Added to the "
             "registry 2026-07-31: it was running and undeclared.",
    ),
    RuntimeService(
        name="cognition_cycle",
        kind="process",
        launch="systemd",
        role="Deep cognition cycle — soveryn-cognition-cycle.service "
             "(python -m soveryn.agents.cognition), POSTs to the cognition "
             "surface :8089. Declared as an app.py thread from 2026-06-22 and "
             "never wired; no cycle ran until 2026-07-31. Gated off by "
             "SOVERYN_COGNITION_CYCLE_ENABLED. NOTE: distinct from "
             "soveryn-cognition.service, which is the MODEL SERVER on :8089.",
    ),
    RuntimeService(
        name="dream_aetheria",
        kind="process",
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
    return server.base_url


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
    # Messages contacts must be active chat agents (not overnight inboxes)
    bad_msg = set(MESSAGES_CONTACTS) - set(ACTIVE_AGENTS)
    if bad_msg:
        raise RuntimeError(f"MESSAGES_CONTACTS not in ACTIVE_AGENTS: {bad_msg}")
    parked_overlap = set(MESSAGES_CONTACTS) & MESSAGES_PARKED
    if parked_overlap:
        raise RuntimeError(f"MESSAGES_CONTACTS overlaps PARKED: {parked_overlap}")
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
    """Every port the active fleet should be listening on (excluding APP_PORT).

    External backends (skip_preflight) are omitted — they are not sockets.
    """
    return frozenset(
        {s.port for s in MODEL_SERVERS if not s.skip_preflight}
        | {e.port for e in SERVICE_ENDPOINTS}
    )


_validate()
