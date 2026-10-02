"""SOVERYN vNext — UI compatibility REST endpoints.

Real implementations of /api/models and /api/persona/* off existing data.
The old /api/message_board and /api/research_journal stubs were removed
(no UI or JS caller). Unmirrored production routes 404 via the global
handler in soveryn/app/startup.py:
  /api/memory/evidence    — TODO(vnext-memory-evidence): needs memory router
  WebSocket vision_frame  — TODO(vnext-perception-ws): needs SocketIO + perception layer
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
