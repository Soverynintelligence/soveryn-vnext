"""SOVERYN vNext — Flask app factory.

create_app(env=None, conv_store=None) -> Flask

Wires together the existing layers (runtime config, conversation store,
AgentLoop per active agent) into an HTTP surface. Factory only — never
calls app.run(). The CLI launcher (out of scope this commit) will own
the actual binding.

Localhost guard: rejects non-127.0.0.1 by default. Bypass via
app.config['SOVERYN_REQUIRE_LOCALHOST'] = False (NEVER env var).

Per-request state lives on flask.g; app-wide state lives on
app.extensions['soveryn']:
  - env: EnvConfig
  - conv_store: ConversationStore
  - agent_loops: dict[str, AgentLoop]
"""

from __future__ import annotations
import logging
from typing import Any

from flask import Flask, g, jsonify, request

from soveryn import __version__
from soveryn.agents.loop import AgentLoop, _default_embed
from soveryn.config.loader import EnvConfig, load_env_config
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.tools.registry import ToolRegistry


logger = logging.getLogger(__name__)


def create_app(
    env: EnvConfig | None = None,
    conv_store: ConversationStore | None = None,
    agent_loops: dict[str, AgentLoop] | None = None,
) -> Flask:
    """Build a Flask app instance with all routes wired.

    All three injected args have sensible defaults so production code can
    just call create_app() — tests inject everything for isolation.
    """
    app = Flask("soveryn")
    app.config.setdefault("SOVERYN_REQUIRE_LOCALHOST", True)
    app.config.setdefault("SOVERYN_VERSION", __version__)
    app.config.setdefault(
        "SOVERYN_LEGACY_TEMPLATES_DIR",
        "/home/jon-deoliveira/soveryn_complete/templates",
    )

    env = env if env is not None else load_env_config()
    if conv_store is None:
        conv_store = ConversationStore(env.conversations_db)
    tool_registry = None
    coord_store = None
    coord_event_bus = None
    coord_worker = None
    if agent_loops is None:
        # Pinned memory is Aetheria-only by design — it's her relationship
        # substrate (facts about Jon, the project, her continuity). Vett and
        # Scotty don't get it (different scopes, different prompt budgets).
        pinned_path = env.pinned_memory_path
        if not pinned_path.is_file():
            raise FileNotFoundError(
                f"pinned_memory.md missing at {pinned_path}; "
                f"set SOVERYN_PINNED_MEMORY_PATH or place the file at the default location"
            )
        pinned_text = pinned_path.read_text(encoding="utf-8")

        # Recall wiring (Aetheria only). Prod lattice remains the embedding
        # recall source; vnext lattice supplies the reviewed identity spine.
        # Both are read-only in AgentLoop. Writes stay out of live recall.
        recall_lattice = None
        identity_spine_lattice = None
        if env.recall_lattice_db.is_file():
            from soveryn.memory.lattice import LatticeStore
            recall_lattice = LatticeStore(env.recall_lattice_db)
            if env.lattice_db.is_file():
                identity_spine_lattice = LatticeStore(env.lattice_db)
        else:
            logger.warning(
                "recall_lattice_db missing at %s — Aetheria will run without recall",
                env.recall_lattice_db,
            )

        tool_registry = ToolRegistry()
        if recall_lattice is not None:
            from soveryn.agents.aetheria.tools import register_aetheria_tools

            register_aetheria_tools(
                tool_registry,
                recall_lattice=recall_lattice,
                embed_fn=_default_embed,
            )

        # Coordination Boards — register the four board tools for all three
        # agents per the locked spec (Aetheria 2026-06-01). The CoordinationStore
        # composes over the consolidated lattice DB (env.lattice_db == recall
        # path post-consolidation 2026-06-01 / vnext 7d75535). Vett, Aetheria,
        # and Scotty all get full read+write grant. Friction arbitration is
        # enforced at the persona/relational layer, not the tool layer — any
        # agent can OPEN a Friction node; resolution flows through Aetheria.
        coord_store = None
        coord_event_bus = None
        if env.lattice_db.is_file():
            from soveryn.platform.coordination import CoordinationStore
            from soveryn.platform.coordination.events import InMemoryEventBus
            from soveryn.platform.coordination.tools import register_coord_tools

            # Phase E: wire an InMemoryEventBus into the store so mutations
            # emit CoordEvents. The worker thread (started below, after
            # agent_loops are built) drains the bus and dispatches per the
            # routing rules.
            coord_event_bus = InMemoryEventBus()
            coord_store = CoordinationStore(env.lattice_db, event_bus=coord_event_bus)
            for agent_name in ("aetheria", "vett", "scotty"):
                register_coord_tools(
                    tool_registry,
                    coord_store=coord_store,
                    owner_agent=agent_name,
                    grant_write=True,
                )

        # Scotty's bounded mechanical tools (read-only observation surface:
        # read_file, list_directory, git_status, git_diff, run_pytest).
        # Path-allowlisted to SCOTTY_PROJECT_ROOT, size/time/output capped.
        # Detect + Verify shipped; Fix + Rollback (write tools) still queued.
        from soveryn.agents.scotty.tools import (
            build_list_directory_tool,
            build_read_file_tool,
            register_scotty_tools,
        )
        register_scotty_tools(tool_registry)
        # Aetheria gets read_file + list_directory too (2026-06-03), so she can
        # reference her own design docs (docs/superpowers/specs/) and the code
        # that implements her behavior. Same path allow-list as Scotty (vnext
        # repo only, no /etc, no credentialed paths). She does NOT get
        # git/pytest tools — those are Scotty's executor surface, not hers.
        tool_registry.register(build_read_file_tool(owner_agent="aetheria"))
        tool_registry.register(build_list_directory_tool(owner_agent="aetheria"))

        # Library layer tools — shared write surface for verified reference
        # material (per the 2026-06-02 design discussion, "Option B": passive
        # surface, library writes don't fire coord webhooks, agents see new
        # entries via heartbeat lattice-activity summary). All three agents
        # get write+search; the library is reference material owned by no
        # single agent, with author attribution preserved on each node.
        if recall_lattice is not None:
            from soveryn.platform.library import register_library_tools
            for agent_name in ("aetheria", "vett", "scotty"):
                register_library_tools(
                    tool_registry,
                    lattice_store=recall_lattice,
                    embed_fn=_default_embed,
                    owner_agent=agent_name,
                )

        # recent_self_audit — closes the introspection gap surfaced 2026-06-03:
        # agents can't see intermediate tool calls in their conversation
        # history (AgentLoop.save_turn persists user/assistant only). This
        # tool returns their own recent actions from the audit log
        # (coord_event_log + coord_references + library writes) so they can
        # verify what they actually did rather than relying on filtered
        # context. Registered for all three agents.
        if env.lattice_db.is_file():
            from soveryn.platform.audit import register_audit_tools
            for agent_name in ("aetheria", "vett", "scotty"):
                register_audit_tools(
                    tool_registry,
                    lattice_db_path=env.lattice_db,
                    owner_agent=agent_name,
                )

        # Web tools (web_search + fetch_url) — Aetheria and Vett only.
        # Backed by local SearXNG (:8095 default) for sovereign metasearch
        # and trafilatura for main-content extraction. SSRF guard rejects
        # private/loopback/link-local IPs in fetch so the model can't be
        # social-engineered into hitting internal services. Scotty does NOT
        # get these — his surface is mechanical local-host tools, not
        # arbitrary outbound network.
        import os
        searxng_url = os.environ.get(
            "SOVERYN_SEARXNG_URL", "http://127.0.0.1:8095/",
        )
        from soveryn.platform.web import register_web_tools
        for agent_name in ("aetheria", "vett"):
            register_web_tools(
                tool_registry,
                searxng_url=searxng_url,
                owner_agent=agent_name,
            )

        # Vett's patrol tools (read_patrol_sources + mark_source_visited).
        # These read the static YAML source list and update per-source state
        # in vett_patrol_state — only Vett gets them; Aetheria isn't in the
        # patrol workflow even though she has web_search/fetch_url.
        if env.lattice_db.is_file():
            from soveryn.agents.vett.tools import register_vett_patrol_tools
            register_vett_patrol_tools(
                tool_registry,
                lattice_db_path=env.lattice_db,
            )

        agent_loops = {}
        for name in ACTIVE_AGENTS:
            kwargs = {"soul_text": None}
            # Every active agent gets the shared tool_registry. Each agent's
            # _tool_schemas() filters to only its own owner-keyed tools, so
            # sharing the registry doesn't leak capability across agents.
            kwargs["tool_registry"] = tool_registry
            if name == "aetheria":
                kwargs["pinned_text"] = pinned_text
                if recall_lattice is not None:
                    kwargs["lattice_store"] = recall_lattice
                    if identity_spine_lattice is not None:
                        kwargs["identity_spine_store"] = identity_spine_lattice
                    kwargs["recall_k"] = 5
                    kwargs["recall_threshold"] = 0.70
                    # embed_fn defaults to _default_embed (calls :8086 nomic-embed)
                # History budget — leave 12K of Gemma 4 31B's 32K window for
                # response generation so long sessions don't push her into the
                # "stuck thinking, no answer" failure mode. context_window is
                # the UI denominator for the pressure bar, not enforced here.
                # Both lines update together when the model swaps.
                kwargs["history_token_budget"] = 20_000
                kwargs["context_window"] = 32_768
                # thinking_budget_tokens left unset (None = unrestricted).
                # As of 2026-06-01 Aetheria runs on Gemma 4 31B (vanilla Google
                # instruct) with thinking disabled via chat-template-kwargs in
                # router-presets.ini. Reason: llama.cpp's generic reasoning
                # extractor doesn't have model-specific parsers — Qwen3-A3B
                # bleeds and Gemma's <|channel>thought consumes all output.
                # The proper fix (per-model parsers like vLLM's --reasoning-parser
                # qwen3) lands when Aetheria moves to vLLM on uniform-Blackwell
                # hardware (Spark arrival, all-Blackwell roadmap). Until then,
                # thinking stays off across whichever model carries her.
            agent_loops[name] = AgentLoop(name, conv_store, **kwargs)

        # Phase E: start the coord event worker now that agent_loops exists.
        # Worker pulls from coord_event_bus and dispatches to webhook sessions.
        # Dispatcher composes over agent_loops + conv_store; webhook sessions
        # are durable per-agent (lazily created on first use).
        coord_worker = None
        if coord_event_bus is not None:
            from soveryn.platform.coordination.dispatcher import AgentDispatcher
            from soveryn.platform.coordination.worker import CoordEventWorker
            dispatcher = AgentDispatcher(agent_loops, conv_store)
            coord_worker = CoordEventWorker(
                coord_event_bus, dispatcher, lattice_db_path=env.lattice_db,
            )
            coord_worker.start()

    app.extensions["soveryn"] = {
        "env": env,
        "conv_store": conv_store,
        "agent_loops": agent_loops,
        "tool_registry": tool_registry,
        "coord_store": coord_store,
        "coord_event_bus": coord_event_bus,
        "coord_worker": coord_worker,
    }

    _register_guards(app)
    _register_error_handlers(app)
    _register_blueprints(app)

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Guards
# ─────────────────────────────────────────────────────────────────────────────

def _register_guards(app: Flask) -> None:

    @app.before_request
    def _require_localhost():
        if not app.config["SOVERYN_REQUIRE_LOCALHOST"]:
            return None
        remote = (request.remote_addr or "").strip()
        if remote in ("127.0.0.1", "::1"):
            return None
        return _error_response(
            "localhost_required",
            f"Requests must originate from 127.0.0.1 (got {remote!r})",
            403,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Error envelope
# ─────────────────────────────────────────────────────────────────────────────

def _error_response(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _register_error_handlers(app: Flask) -> None:

    @app.errorhandler(404)
    def _not_found(_e):
        return _error_response("not_found", "No such route", 404)

    @app.errorhandler(405)
    def _bad_method(_e):
        return _error_response("method_not_allowed", "Wrong HTTP method", 405)

    @app.errorhandler(Exception)
    def _unhandled(e):
        # Don't leak internals; log full and return generic envelope.
        logger.exception("unhandled exception in request")
        return _error_response("internal_error", "Unhandled server error", 500)


# ─────────────────────────────────────────────────────────────────────────────
# Blueprint registration
# ─────────────────────────────────────────────────────────────────────────────

def _register_blueprints(app: Flask) -> None:
    from soveryn.app.routes.chat import bp as chat_bp
    from soveryn.app.routes.compat import bp as compat_bp
    from soveryn.app.routes.health import bp as health_bp
    from soveryn.app.routes.ui import bp as ui_bp
    from soveryn.app.routes.ui_compat import bp as ui_compat_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(compat_bp)
    from soveryn.app.routes.api_system import bp as api_system_bp
    app.register_blueprint(api_system_bp)
    from soveryn.app.routes.api_memory import bp as api_memory_bp
    app.register_blueprint(api_memory_bp)
    # Register ui_bp BEFORE ui_compat_bp so / is owned by the native UI.
    # The legacy bridge owns /legacy and /legacy/mobile only.
    app.register_blueprint(ui_bp)
    app.register_blueprint(ui_compat_bp)
