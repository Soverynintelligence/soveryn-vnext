"""SOVERYN vNext — UI compatibility REST endpoints.

These exist so the existing desktop UI doesn't break when pointed at
vNext on :5001. Two are real implementations (models, personas) off
existing data. Three are explicit stubs (message_board GET, clear, and
research_journal) marked with `_stub: true` so consumers — including
side-by-side compare — can tell what hasn't been implemented yet.

Two production routes are NOT mirrored:
  /api/memory/evidence    — TODO(vnext-memory-evidence): needs memory router
  WebSocket vision_frame  — TODO(vnext-perception-ws): needs SocketIO + perception layer

The UI will get a clean JSON 404 envelope for those, courtesy of the
global error handler in soveryn/app/startup.py.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from soveryn.agents.personas import (
    PersonaError,
    baked_persona,
    clear_persona_override,
    get_persona,
    persona_source,
    save_persona_override,
)
from soveryn.app.routes.chat import _resolve_agent
from soveryn.config.runtime import (
    ACTIVE_AGENTS, AGENT_TO_SERVER, MODEL_SERVERS, RETIRED,
)


bp = Blueprint("compat", __name__)


def _err(code: str, message: str, status: int):
    """Mirrors the envelope used in routes/chat.py for consistency."""
    return jsonify({"error": {"code": code, "message": message}}), status


# ─── /api/models  (REAL — flat production-compatible map) ────────────────────

@bp.get("/api/models")
def api_models():
    """Return {agent: model_filename.gguf} for every active agent.

    Production-compatible flat shape. Filename is the GGUF basename
    derived from the MODEL_SERVERS entry the agent routes to.
    """
    server_by_name = {s.name: s for s in MODEL_SERVERS}
    out: dict[str, str] = {}
    for agent_name in ACTIVE_AGENTS:
        server_label = AGENT_TO_SERVER.get(agent_name)
        if not server_label:
            continue
        server = server_by_name.get(server_label)
        if not server:
            continue
        out[agent_name] = server.model_path.name  # basename of GGUF
    return jsonify(out), 200


# ─── /api/persona/<agent>  (REAL — production-compatible shape) ──────────────

def _hot_reload_persona(agent: str, text: str) -> None:
    """Push edited persona into the live AgentLoop if the app has one."""
    try:
        ext = current_app.extensions.get("soveryn") or {}
        loops = ext.get("agent_loops") or {}
        loop = loops.get(agent)
        if loop is not None:
            loop.system_prompt = text
    except Exception:
        # Best-effort — disk write already succeeded.
        pass


@bp.get("/api/persona/<agent_name>")
def api_persona(agent_name: str):
    """Return {agent, persona, source, baked} for an active agent.

    ``source`` is ``override`` when a disk edit is active, else ``baked``.
    ``baked`` is always the committed default (for Reset in the UI).
    """
    agent, err = _resolve_agent(agent_name)
    if err:
        return err
    try:
        text = get_persona(agent)
        source = persona_source(agent)
        baked = baked_persona(agent)
    except PersonaError as e:
        return _err("internal_error", f"persona lookup failed: {e}", 500)
    return jsonify({
        "agent": agent,
        "persona": text,
        "source": source,
        "baked": baked,
    }), 200


@bp.put("/api/persona/<agent_name>")
def api_persona_put(agent_name: str):
    """Save a persona override and hot-reload the live agent loop."""
    agent, err = _resolve_agent(agent_name)
    if err:
        return err
    body = request.get_json(silent=True) or {}
    text = body.get("persona")
    if not isinstance(text, str):
        return _err("bad_request", "body.persona must be a string", 400)
    try:
        save_persona_override(agent, text)
        effective = get_persona(agent)
    except PersonaError as e:
        return _err("bad_request", str(e), 400)
    _hot_reload_persona(agent, effective)
    return jsonify({
        "ok": True,
        "agent": agent,
        "persona": effective,
        "source": "override",
        "baked": baked_persona(agent),
    }), 200


@bp.delete("/api/persona/<agent_name>")
def api_persona_delete(agent_name: str):
    """Clear override and restore the baked-in persona."""
    agent, err = _resolve_agent(agent_name)
    if err:
        return err
    clear_persona_override(agent)
    text = get_persona(agent)
    _hot_reload_persona(agent, text)
    return jsonify({
        "ok": True,
        "agent": agent,
        "persona": text,
        "source": "baked",
        "baked": baked_persona(agent),
    }), 200


# ─── /api/message_board  (STUB — TODO(vnext-message-board)) ──────────────────

@bp.get("/api/message_board")
def api_message_board():
    """STUB: returns empty inbox per agent.

    Real implementation needs the agent_message_board untracked infra ported
    to vNext. TODO(vnext-message-board).

    With ?agent=X: returns {"<X>": []} after active-agent validation.
    Without ?agent: returns {agent: []} for every active agent.
    """
    requested = request.args.get("agent")
    if requested is not None and requested.strip():
        agent, err = _resolve_agent(requested)
        if err:
            return err
        return jsonify({"_stub": True, agent: []}), 200
    return jsonify({"_stub": True, **{a: [] for a in sorted(ACTIVE_AGENTS)}}), 200


@bp.post("/api/message_board/clear")
def api_message_board_clear():
    """STUB: does NOT touch state. TODO(vnext-message-board)."""
    return jsonify({
        "_stub": True,
        "deleted": [],
        "message": "message board not implemented in vNext yet",
    }), 200


# ─── /api/research_journal  (STUB — TODO(vnext-research-journal)) ────────────

@bp.get("/api/research_journal")
def api_research_journal():
    """STUB: returns empty content.

    Production reads soveryn_memory/aetheria_research_journal.md. vNext
    will need its own write path before this becomes real.
    TODO(vnext-research-journal).
    """
    return jsonify({"_stub": True, "content": ""}), 200
