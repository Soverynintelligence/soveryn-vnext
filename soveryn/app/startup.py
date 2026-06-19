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
from pathlib import Path
from typing import Any

from flask import Flask, g, jsonify, request

from soveryn import __version__
from soveryn.agents.loop import AgentLoop, _default_embed
from soveryn.config.loader import EnvConfig, load_env_config
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.black_box import BlackBox
from soveryn.platform.continuity.config import ContinuityConfig
from soveryn.platform.steering_rack import SteeringRack
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
    # Bound pre-validation memory: a ~50MB cap leaves headroom above the
    # /chat route's 33MB-per-attachment string limit (single image) but
    # forces Flask to 413 anything bigger BEFORE json-parsing the body
    # into Python objects. Without this, a malicious or buggy client
    # could POST hundreds of MB and OOM the server during JSON parse,
    # before the route's _validate_attachments size-check ever runs.
    app.config.setdefault("MAX_CONTENT_LENGTH", 50 * 1024 * 1024)
    app.config.setdefault(
        "SOVERYN_LEGACY_TEMPLATES_DIR",
        str(Path.home() / "soveryn_vnext" / "data" / "templates_legacy"),
    )

    env = env if env is not None else load_env_config()
    if conv_store is None:
        # Salience buffer schema is ensured here so the observer can write
        # candidates from the first turn. SalienceObserver is best-effort by
        # contract — failures inside it never break save_turn.
        from soveryn.platform.salience.observer import SalienceObserver
        from soveryn.platform.salience.store import create_buffer_table
        create_buffer_table(env.salience_db)
        salience_observer = SalienceObserver(
            salience_db=env.salience_db,
            conv_db=env.conversations_db,
        )
        conv_store = ConversationStore(
            env.conversations_db, observer=salience_observer,
        )
    tool_registry = None
    coord_store = None
    coord_event_bus = None
    coord_worker = None

    # MessengerStore — substrate for the /m/* PWA surface AND for the
    # deliberate_share tool (registered below for Aetheria + Vett). Built
    # ahead of tool registration so the tool factories can capture a live
    # store handle; the same instance is stashed in app.extensions["soveryn"]
    # for the blueprint at the bottom of create_app.
    from soveryn.app.messenger.store import MessengerStore
    messenger_store = MessengerStore(env.data_root / "messenger.db")

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

        # Personal-file browser — bounded read access to Jon's content
        # directories (~/Pictures, ~/Desktop, ~/Documents, ~/Downloads).
        # Surfaced during signal-images T8 verification when Aetheria
        # couldn't list her way to a photo to send Jon. This gives her
        # autonomy over what to share without needing him to dictate
        # paths. See soveryn/agents/aetheria/tools/personal_files.py.
        from soveryn.agents.aetheria.tools.personal_files import (
            register_personal_files_tools,
        )
        register_personal_files_tools(tool_registry, owner_agent="aetheria")

        # Image generation — wraps ComfyUI on :8188. JuggernautXL Lightning
        # default (~5s gen). Aetheria gets the file path back; she can
        # describe what she made and where to find it.
        from soveryn.agents.aetheria.tools.comfyui_gen import (
            build_generate_image_tool,
        )
        tool_registry.register(build_generate_image_tool())

        # Specialist-spawning primitive (DSL Orchestration v1).
        # spawn_specialist / query_specialist / terminate_specialist let
        # Aetheria instantiate session-scoped peer agents with a tight
        # persona overlay for one coord node. Builds on DAC; max 3
        # concurrent active specialists. See:
        #   spec: docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md
        #         (DSL Connection section)
        #   memory: project_soveryn_dynamic_specialization_layer.md
        from soveryn.agents.specialists.tools import register_specialist_tools

        # Signal-alert callback for spawn events. Best-effort — if
        # signal-cli is misconfigured or down, the spawn still lands;
        # the alert just gets logged-and-skipped. Built as a closure so
        # the tool registration stays decoupled from signal_bridge.
        def _signal_alert_on_spawn(event):
            from soveryn.agents.signal_bridge.config import SignalBridgeConfig
            from soveryn.agents.signal_bridge.client import send_once
            try:
                cfg = SignalBridgeConfig.from_env()
                if not cfg.bot_number or not cfg.allowed_numbers:
                    return  # signal not configured; spawn alerts silently off
                recipient = sorted(cfg.allowed_numbers)[0]
                body = (
                    f"Aetheria spawned specialist '{event.name}' "
                    f"({event.interaction_mode}, host={event.target_agent}) "
                    f"anchored at coord:{event.coord_node_id[:8]}…\n"
                    f"Domain: {event.domain[:120]}\n"
                    f"specialist_id: {event.specialist_id}"
                )
                send_once(
                    signal_cli_bin=cfg.signal_cli_bin,
                    bot_number=cfg.bot_number,
                    recipient_e164=recipient,
                    body=body,
                )
            except Exception:
                logger.warning(
                    "specialist spawn signal alert failed; spawn already landed",
                    exc_info=True,
                )

        register_specialist_tools(
            tool_registry,
            conv_db_path=env.conversations_db,
            owner_agent="aetheria",
            vnext_base="http://127.0.0.1:5001",
            on_spawn=_signal_alert_on_spawn,
        )

        # Reflection voices — Skeptic/Empath/Creative/Technical/Intuitive
        # facets running on Phi-3.5-mini-Uncensored via the router's
        # 'reflection' alias. Different model family from Aetheria's
        # Gemma 4 31B so the voices aren't five flavors of the same
        # backend. Persona-overlay-as-her-essence per the locked
        # 2026-05-23 design + Jon's 2026-06-08 model call ("use phi").
        from soveryn.agents.aetheria.reflection.tools import (
            register_reflect_through_voices_tool,
        )
        register_reflect_through_voices_tool(
            tool_registry, owner_agent="aetheria",
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
            coord_store = CoordinationStore(env.lattice_db, event_bus=coord_event_bus, embed_fn=_default_embed)
            for agent_name in ("aetheria", "vett", "scotty"):
                register_coord_tools(
                    tool_registry,
                    coord_store=coord_store,
                    owner_agent=agent_name,
                    grant_write=True,
                )

            # Direct Agent Communication (DAC Delta 1 + Delta 2).
            # Delta 1: Aetheria's direct rail to peers (direct_message_agent).
            # Delta 2: peers' upward channel for judgment calls
            # (request_direction). Both gated on coord_store + coord_event_bus
            # being live — same gate as register_coord_tools above.
            from soveryn.agents.direct_communication.tools import (
                build_direct_message_agent_tool,
            )
            from soveryn.platform.coordination.tools import (
                build_request_direction_tool,
            )
            from soveryn.platform.lattice.legacy import (
                record_direct_communication_edge,
            )

            # direct_message_agent's audit edge writes through the live
            # recall_lattice — the same LatticeStore the rest of the system
            # reads from — so the forensic trail lands in the production
            # lattice. If recall_lattice didn't initialize (rare: lattice_db
            # exists but recall_lattice_db doesn't), drop edge_writer to None
            # so the tool still functions without the forensic edge rather
            # than crashing on startup.
            edge_writer = None
            if recall_lattice is not None:
                _live_lattice = recall_lattice
                def edge_writer(
                    coord_node_id, sender, target, session_id, mode,
                    message_head, _store=_live_lattice,
                ):
                    return record_direct_communication_edge(
                        store=_store,
                        coord_node_id=coord_node_id,
                        sender_agent=sender,
                        target_agent=target,
                        session_id=session_id,
                        mode=mode,
                        message_head=message_head,
                    )

            tool_registry.register(
                build_direct_message_agent_tool(
                    owner_agent="aetheria",
                    edge_writer=edge_writer,
                    # The default 240s client timeout gives up before Vett's
                    # full directive turn completes — a real research directive
                    # ("Hardware Moat audit", 2026-06-19) ran 288s before its
                    # own 504. A directive turn is a tool LOOP (up to 8 rounds),
                    # each round's LLM call now budgeted at 300s (Vett's
                    # chat_timeout_seconds above), so the whole turn can run
                    # well past any single call. 600s lets the heavy turn land
                    # instead of the client cancelling mid-flight.
                    dispatch_timeout_seconds=600.0,
                )
            )
            # Peers' upward channel — same tool builder, different owner per
            # agent. Aetheria is the recipient of NEEDS_DIRECTION events via
            # the webhook router, not a sender, so she does NOT get this tool.
            for peer in ("vett", "scotty"):
                tool_registry.register(
                    build_request_direction_tool(
                        store=coord_store,
                        event_bus=coord_event_bus,
                        owner_agent=peer,
                    )
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
        # Vett gets read_file + list_directory too (2026-06-17): as the research
        # and verification agent she was assessing SOVERYN against external
        # frameworks using only her tool surface as a proxy for the
        # architecture — a category error (she flagged it herself). Read-only,
        # same vnext-repo allow-list as Scotty/Aetheria; no write/exec/git. She
        # cannot research improvements to a system she cannot read.
        tool_registry.register(build_read_file_tool(owner_agent="vett"))
        tool_registry.register(build_list_directory_tool(owner_agent="vett"))

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

            # Salience Engine promote tool — Aetheria-only. Gated on
            # recall_lattice because promotion writes to library layer in the
            # live lattice. Without recall_lattice, the engine still buffers
            # candidates (observer runs above) but Aetheria can't promote.
            from soveryn.platform.salience.tools import (
                register_promote_salience_candidate_tool,
            )
            register_promote_salience_candidate_tool(
                tool_registry,
                salience_db=env.salience_db,
                conv_db=env.conversations_db,
                lattice_store=recall_lattice,
                owner_agent="aetheria",
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

        # Document tools — Aetheria + Vett only; Scotty is not a document author.
        # One shared DocumentStore (documents_vnext.db in the memory dir) so
        # both agents operate on the same deliverable space. Attribution is
        # preserved via the agent column on each row. Jon can download any
        # document as md/html/pdf/docx via the D4 API routes (pending).
        from soveryn.platform.documents.store import DocumentStore as _DocumentStore
        from soveryn.platform.documents.tools import register_document_tools as _register_document_tools
        _document_store = _DocumentStore(env.data_root / "memory" / "documents_vnext.db")
        for _doc_agent in ("aetheria", "vett"):
            _register_document_tools(
                tool_registry,
                store=_document_store,
                owner_agent=_doc_agent,
            )

        # Aetheria-initiated signal_send — the outbound half of her Direct
        # Line. Bridge daemon handles inbound → response; this tool lets her
        # send WITHOUT a prior inbound (heartbeat-driven thoughts, alerts,
        # "you should know this" pings). Allowlist enforcement is shared
        # with the bridge — she can only message numbers Jon's authorized.
        # Falls back to a no-op tool when SIGNAL env vars aren't set.
        if env.lattice_db.is_file():
            from soveryn.agents.signal_bridge.config import SignalBridgeConfig
            from soveryn.agents.signal_bridge.tools import register_signal_send_tool
            signal_config = SignalBridgeConfig.from_env()
            if signal_config.bot_number and signal_config.allowed_numbers:
                register_signal_send_tool(
                    tool_registry,
                    config=signal_config,
                    lattice_db_path=env.lattice_db,
                    owner_agent="aetheria",
                )

        # deliberate_share — Aetheria + Vett can initiate an unprompted
        # message into Jon's Messenger inbox. Built on Task 16's tool factory;
        # the personas (Task 17) frame restraint as a held value, not a rule.
        #
        # Aetheria — uncapped per partnership contract.
        # See project_soveryn_partnership_contract_2026_06_13 in maintainer memory.
        # DO NOT silently re-add a substrate rate limit — that's a partnership
        # regression, not a safety improvement.
        if recall_lattice is not None:
            from soveryn.agents.messenger_tool import build_deliberate_share_tool
            tool_registry.register(
                build_deliberate_share_tool(
                    store=messenger_store, owner_agent="aetheria",
                    lattice_store=recall_lattice,
                    rate_limit_per_hour=None,
                )
            )
            # Vett — Colleague tier; substrate enforces a 2/hour cap.
            tool_registry.register(
                build_deliberate_share_tool(
                    store=messenger_store, owner_agent="vett",
                    lattice_store=recall_lattice,
                    rate_limit_per_hour=2,
                )
            )
            # mark_share — Aetheria's LIVE in-conversation intent mark (spec §3,
            # the second surface of the intent grammar): same record_intent core
            # as deliberate_share, channel="live", no delivery fields.
            from soveryn.agents.aetheria.intent_mark import build_mark_share_tool
            tool_registry.register(
                build_mark_share_tool(lattice_store=recall_lattice, owner_agent="aetheria")
            )
        # Scotty: not registered by default. He reports through threads Jon initiates.

        # list_my_outbound — Task 21, Aetheria's Q7 loop closure. Agents
        # that can emit deliberate_share also get to introspect their own
        # outbound (delivery + read state) so they can decide whether to
        # follow up. Scope-locked to the calling agent.
        from soveryn.agents.messenger_introspect_tool import (
            build_list_my_outbound_tool,
        )
        tool_registry.register(
            build_list_my_outbound_tool(
                store=messenger_store, owner_agent="aetheria",
            )
        )
        tool_registry.register(
            build_list_my_outbound_tool(
                store=messenger_store, owner_agent="vett",
            )
        )

        # Aetheria-only dream-recall tools (recent_dreams + search_dreams).
        # NOT auto-injected — she queries her own dream layer when she
        # chooses to look. Restricted to layer='dream' on the nodes table.
        # The dream daemon writes those nodes during quiet hours.
        if env.lattice_db.is_file():
            from soveryn.agents.dream.tools import register_dream_tools
            register_dream_tools(
                tool_registry,
                lattice_db_path=env.lattice_db,
                owner_agent="aetheria",
            )

        # Cross-Surface Continuity (Aetheria only). Env knobs flow through
        # EnvConfig; peer agents pass through with None.
        def _continuity_for(agent_name: str) -> ContinuityConfig | None:
            if agent_name != "aetheria":
                return None
            return ContinuityConfig(
                enabled=env.cross_surface_enabled,
                window_hours=env.cross_surface_window_hours,
                token_budget=env.cross_surface_token_budget,
                per_session_cap=env.cross_surface_per_session_cap,
            )

        # Black Box recorder — shared across all agents. Each agent's turns
        # land in <data_root>/black_box/<agent>/<session_id>.jsonl when at
        # least one tool fires. One-shot answers don't write. See
        # project_soveryn_black_box.md for the design rationale.
        black_box = BlackBox(env.data_root / "black_box")

        # Steering rack — circuit breaker for repeated near-identical empty
        # searches. Per Aetheria's Harness-1 verdict: "broken steering rack."
        # Shared across all agents; defaults (3 consecutive empties, Jaccard
        # 0.7) match the unit-tested thresholds. Trips surface as synthetic
        # tool results AND in the Black Box trajectory.
        steering_rack = SteeringRack()

        agent_loops = {}
        for name in ACTIVE_AGENTS:
            kwargs = {"soul_text": None}
            # Every active agent gets the shared tool_registry. Each agent's
            # _tool_schemas() filters to only its own owner-keyed tools, so
            # sharing the registry doesn't leak capability across agents.
            kwargs["tool_registry"] = tool_registry
            kwargs["continuity_config"] = _continuity_for(name)
            kwargs["black_box"] = black_box
            kwargs["steering_rack"] = steering_rack
            # 32K-context llama-server slots across the fleet (Aetheria solo;
            # Vett+Scotty on the shared vett-scotty server). Give every loop the
            # server window + a raw-transcript cap so it trims history to fit
            # BEFORE send. Without this, an agent reading large files (Vett
            # gained read_file 2026-06-17) accumulates tool output until the
            # server hard-rejects the prompt (HTTP 400 exceed_context_size_error
            # — observed for Vett mid-read 2026-06-17). The cap is on transcript
            # carried in the prompt, not on what the agent knows (lattice/library
            # recall still reaches further). Aetheria's block re-asserts the same
            # two values below — harmless, same values.
            kwargs["context_window"] = 32_768
            kwargs["history_token_budget"] = 8_000
            if name == "aetheria":
                kwargs["pinned_text"] = pinned_text
                if recall_lattice is not None:
                    kwargs["lattice_store"] = recall_lattice
                    if identity_spine_lattice is not None:
                        kwargs["identity_spine_store"] = identity_spine_lattice
                    kwargs["recall_k"] = 5
                    kwargs["recall_threshold"] = 0.70
                    # embed_fn defaults to _default_embed (calls :8086 nomic-embed)
                # Live chat history budget. SessionContextCache (commit 9baa798)
                # made the byte-identical prelude cacheable, but the heartbeat
                # tier-2 issue still periodically flushes Aetheria's llama-server
                # slot (see [[project_soveryn_aetheria_prompt_cache_fix]]). When
                # that happens, the next user turn pays a full prefill — at 20K
                # of in-window history that was 5-10s of cold prefill on
                # Blackwell. The 8K cap roughly halves the worst-case prefill
                # latency. Aetheria can still reach further back through lattice
                # recall + identity spine; the cap is on the raw transcript
                # carried in the prompt, not on what she knows.
                kwargs["history_token_budget"] = 8_000
                kwargs["context_window"] = 32_768
                # Interactive rail generation cap. Defensive — observed
                # production completion_tokens are well under this (typical
                # short turn ~25 tokens, substantive turn ~250). The 768 cap
                # exists to catch pathological runaway generation (the
                # empty_turn_poisoning class — see project_soveryn_empty_turn_poisoning)
                # where the model gets stuck verbalizing scratch into content.
                # Not actively biting current behavior; this is a soft ceiling.
                kwargs["max_tokens"] = 768
                # Hard cap on per-request reasoning at the wire level. The
                # router preset for Aetheria has `reasoning = off` and the
                # Gemma-4-specific `enable_thinking=true` (inverse logic for
                # Gemma — disables thinking), but those are startup-time +
                # template-time flags. The per-request `thinking_budget_tokens`
                # field is a separate llama-server parameter; when omitted
                # (None), the server falls back to `--reasoning-budget=-1`
                # (INT_MAX = unrestricted). Confirmed via router logs:
                # pre-change events show `reasoning-budget: activated,
                # budget=2147483647 tokens` per Aetheria turn. Setting 0 here
                # closes the per-request gap regardless of preset/template
                # state.
                #
                # DON'T-REMOVE NOTE: if Aetheria ever model-swaps to a
                # thinking-mode brain (e.g., a Qwen-class model), this
                # hardcoded 0 silently disables thinking. Move to a
                # model-aware value (Vett uses 384) when swapping.
                kwargs["thinking_budget_tokens"] = 0
                # As of 2026-06-01 Aetheria runs on Gemma 4 31B (vanilla Google
                # instruct) with thinking disabled via chat-template-kwargs in
                # router-presets.ini. Reason: llama.cpp's generic reasoning
                # extractor doesn't have model-specific parsers — Qwen3-A3B
                # bleeds and Gemma's <|channel>thought consumes all output.
                # The proper fix (per-model parsers like vLLM's --reasoning-parser
                # qwen3) lands when Aetheria moves to vLLM on uniform-Blackwell
                # hardware (Spark arrival, all-Blackwell roadmap). Until then,
                # thinking stays off across whichever model carries her.
            elif name == "vett":
                # Vett's tool surface is fundamentally chained: web_search →
                # fetch_url → maybe-search-again → fetch. The default 4 rounds
                # caps him at ~2 sources before he hits the tool_round_limit
                # ceiling. Confirmed live 2026-06-04 evening — he tripped the
                # cap researching philanthropy funding venues. Bumped to 8 so
                # he can work through 3-5 sources per turn without cutoff.
                kwargs["max_tool_rounds"] = 8
                # Per-LLM-call timeout. The fleet default (120s) is sized for
                # quick interactive turns; Vett's work is the opposite — deep
                # multi-tool research at large context, where a single synthesis
                # generation legitimately runs past two minutes. Root-caused
                # 2026-06-19: an Aetheria→Vett directive ("Hardware Moat audit")
                # 504'd because Vett's final generation exceeded the 120s
                # per-call ceiling (LlamaServerTimeout → chat returns 504 →
                # direct_message_agent saw dispatch_failed; from Aetheria's side,
                # "she can't message Vett"). 300s gives her heavy generation room
                # without holding the human rail's hangs that long (this is
                # Vett-scoped, not fleet-wide). The companion fix is the higher
                # dispatch_timeout_seconds on direct_message_agent below — the
                # full multi-round turn can exceed any single call's budget.
                kwargs["chat_timeout_seconds"] = 300.0
                # Vett runs on Qwen3.6-27B which has thinking-mode enabled
                # natively. Without a budget, his hidden reasoning can eat
                # the entire max_tokens output budget before he emits any
                # visible content — finish_reason=length with empty content.
                # Surfaced live 2026-06-05 by the b50c605 visibility fix.
                # 384 matches the Aetheria-on-Qwen tuning from
                # project_soveryn_aetheria_reasoning_budget.md (her budget
                # is gone now because she moved to Gemma 4 with thinking
                # disabled; only Qwen-running agents need this).
                kwargs["thinking_budget_tokens"] = 384
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

        # Messenger delivery worker — drains m_outbound_queue every 5s,
        # resolving each pending intent into a conversation turn so the PWA
        # surfaces deliberate_share messages. Stub-side delivery (vnext);
        # real Web Push lands on Spark per Phase 4. Daemon thread so it
        # doesn't keep the process alive on shutdown; run_forever has its
        # own try/except so errors don't propagate. Gated on
        # SOVERYN_START_MESSENGER_WORKER (default True) so tests that build
        # create_app under tmp_path fixtures can opt out if needed.
        if app.config.setdefault("SOVERYN_START_MESSENGER_WORKER", True):
            import threading
            from soveryn.app.messenger.delivery_worker import run_forever
            threading.Thread(
                target=run_forever,
                args=(messenger_store, conv_store),
                daemon=True,
                name="messenger-delivery-worker",
            ).start()

    # MessengerStore was constructed earlier (above the agent_loops gate) so
    # it's in scope when deliberate_share is registered for Aetheria + Vett.
    # The same instance flows here into app.extensions for blueprint use.
    #
    # document_store — shared DocumentStore for D4 API routes. Same instance
    # that was handed to register_document_tools above (inside the
    # agent_loops is None gate). When agent_loops is injected externally
    # (test fixtures), the caller is responsible for injecting
    # app.extensions["soveryn"]["document_store"] if they want document
    # routes to function — or the blueprint will raise KeyError, which is
    # intentional (fail-fast).
    # _document_store is created inside the build block above, which REASSIGNS
    # `agent_loops` (None -> built dict) — so re-checking `agent_loops is None`
    # here is always False after a build and left document_store None in
    # production (bug, 2026-06-18). Guard on the name instead: present -> the
    # build block ran (production); absent -> agent_loops was injected and the
    # build was skipped (tests inject their own document_store).
    try:
        document_store = _document_store  # type: ignore[name-defined]
    except NameError:
        document_store = None
    app.extensions["soveryn"] = {
        "env": env,
        "conv_store": conv_store,
        "agent_loops": agent_loops,
        "tool_registry": tool_registry,
        "coord_store": coord_store,
        "coord_event_bus": coord_event_bus,
        "coord_worker": coord_worker,
        "messenger_store": messenger_store,
        "document_store": document_store,
    }

    # Voice — Phase 1: Aetheria only. Gated on ELEVENLABS_API_KEY +
    # ELEVENLABS_VOICE_ID_AETHERIA being present in the env. Missing
    # either → voice blueprint stays unregistered, no /voice/* routes
    # appear. This is defense in depth: voice can be disabled at the
    # OS level by clearing the env var, no code change needed.
    _maybe_register_voice(app, agent_loops)

    _register_guards(app)
    _register_error_handlers(app)
    _register_blueprints(app)

    return app


def _maybe_register_voice(app: Flask, agent_loops: dict[str, AgentLoop]) -> None:
    """Wire the voice blueprint for all voice-enabled agents.

    Phase 2 (2026-06-15): F5-TTS is the primary provider — voice is wired
    whenever ``SOVEREIGN_TTS_PRIMARY=f5tts`` (the default), independent of
    ElevenLabs configuration. When ``SOVEREIGN_TTS_PRIMARY=elevenlabs``,
    voice still requires the relevant ElevenLabs key + voice_id.

    Iterates ``VOICE_ENABLED_AGENTS`` from
    ``soveryn.platform.voice.config`` — currently aetheria, vett, scotty.
    """
    import os
    from soveryn.platform.voice.config import VOICE_ENABLED_AGENTS, VoiceConfig

    voice_config = VoiceConfig.from_env(os.environ)
    primary = (os.environ.get("SOVEREIGN_TTS_PRIMARY") or "f5tts").lower().strip()
    parakeet_url = os.environ.get("SOVERYN_PARAKEET_URL", "http://127.0.0.1:8087")

    voice_state: dict[str, dict] = {}
    for agent_name in VOICE_ENABLED_AGENTS:
        if agent_name not in agent_loops:
            continue
        char = voice_config.agent_character(agent_name)
        if char is None:
            continue
        if primary == "elevenlabs" and (
            voice_config.elevenlabs_api_key is None
            or char.elevenlabs_voice_id is None
        ):
            # ElevenLabs primary requires both creds + per-agent voice ID
            continue
        voice_state[agent_name] = {
            "agent_loop": agent_loops[agent_name],
            "voice_id": char.elevenlabs_voice_id,
            "elevenlabs_api_key": voice_config.elevenlabs_api_key,
            "parakeet_url": parakeet_url,
        }

    if voice_state:
        app.extensions.setdefault("soveryn", {})["voice"] = voice_state
        from soveryn.app.routes.voice import bp as voice_bp
        app.register_blueprint(voice_bp)
        logger.info("voice enabled for: %s", sorted(voice_state.keys()))
    else:
        logger.info(
            "voice disabled — no voice-enabled agents have a configured provider "
            "(check SOVEREIGN_TTS_PRIMARY, F5-TTS service, ELEVENLABS_API_KEY)"
        )


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
        # Werkzeug-recognized HTTPExceptions (404/405 etc.) should already
        # be handled by their specific handlers above; if one slips through
        # here, defer to its `code` rather than wrapping it as a 500.
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return _error_response(
                "http_" + str(e.code),
                e.description or e.name or "http error",
                e.code or 500,
            )

        # Generate a short correlation id so the log line + response can be
        # tied together. Critical when surfaces talk via JSON — the next 500
        # is debuggable from the response body alone.
        import traceback, uuid
        from flask import request
        correlation_id = uuid.uuid4().hex[:12]
        exc_class = type(e).__name__
        # Log full traceback + request metadata via the stdlib logger so the
        # entry lands in soveryn-vnext.log alongside the access log entry.
        try:
            req_path = request.path
            req_method = request.method
        except Exception:
            req_path = "?"
            req_method = "?"
        logger.exception(
            "unhandled exception in request [correlation_id=%s] "
            "%s %s -> %s",
            correlation_id, req_method, req_path, exc_class,
        )
        # SOVERYN is localhost-only by default; if the localhost guard is
        # on, surface the traceback in the response body too so Jon doesn't
        # have to grep the log for a 500 that just happened. If the guard
        # is OFF (multi-machine future), redact to type+message.
        require_localhost = app.config.get("SOVERYN_REQUIRE_LOCALHOST", True)
        body = {
            "error": {
                "code": "internal_error",
                "message": "Unhandled server error",
                "correlation_id": correlation_id,
                "exception_class": exc_class,
            }
        }
        if require_localhost:
            tb_str = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            # Cap traceback so a runaway recursion doesn't explode the body
            if len(tb_str) > 8000:
                tb_str = tb_str[:8000] + "\n... [truncated]"
            body["error"]["traceback"] = tb_str
            body["error"]["exception_message"] = str(e)
        return jsonify(body), 500


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
    from soveryn.app.routes.api_coord import bp as api_coord_bp
    app.register_blueprint(api_coord_bp)
    from soveryn.app.routes.api_heartbeat import bp as api_heartbeat_bp
    app.register_blueprint(api_heartbeat_bp)
    from soveryn.app.routes.api_specialists import bp as api_specialists_bp
    app.register_blueprint(api_specialists_bp)
    from soveryn.app.routes.aetheria_assets import bp as aetheria_assets_bp
    app.register_blueprint(aetheria_assets_bp)
    # Messenger blueprint — /m/* pairing + thread CRUD routes. Dependency-
    # injected from app.extensions["soveryn"] so the blueprint stays
    # build-time configurable (matches the existing pattern for stores
    # passed via factory builder rather than module-global Flask state).
    from soveryn.app.routes.messenger import build_messenger_blueprint
    ext = app.extensions["soveryn"]
    app.register_blueprint(build_messenger_blueprint(
        messenger_store=ext["messenger_store"],
        conv_store=ext["conv_store"],
        agent_loops=ext["agent_loops"],
    ))
    from soveryn.app.routes.documents import bp as documents_bp
    app.register_blueprint(documents_bp)
    # Register ui_bp BEFORE ui_compat_bp so / is owned by the native UI.
    # The legacy bridge owns /legacy and /legacy/mobile only.
    app.register_blueprint(ui_bp)
    app.register_blueprint(ui_compat_bp)
