"""Voice blueprint — /voice landing + /voice/<agent> per-agent voice room.

Roster fold: Aetheria, Eve (Vett's clone), Kernel (Scotty's clone).

WebRTC signaling: POST /voice/<agent>/offer receives the browser's SDP
offer, returns an SDP answer via Pipecat's SmallWebRTCConnection. Per
the 2026-06-10 spike (Q4 + Q7), SmallWebRTCConnection drives the
peer-to-peer transport cleanly from a vanilla Flask view — no FastAPI
sub-app required for Phase 1. The actual Pipecat pipeline (T4
factory) runs as a background asyncio task; the route returns the
signaling answer synchronously.

Templates live under ``soveryn/app/templates/`` (the blueprint declares
``template_folder`` so Jinja resolves voice_landing.html and voice.html
relative to this package, not the Flask app default loader path which
points at ``soveryn/templates/``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
)

from soveryn.app.routes.voice_dispatch import negotiate_and_dispatch_voice


_THIS_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _THIS_DIR.parent / "templates"


# Static assets (orb.css, voice_client.js) live under soveryn/app/static/voice/
# and are served by Flask's app-level static handler at /static/voice/*.
# The blueprint MUST NOT declare its own static_folder/static_url_path —
# doing so registers a duplicate /static/<path> route that conflicts with
# the app-level handler and returns 404 for blueprint-static paths.
bp = Blueprint(
    "voice",
    __name__,
    template_folder=str(_TEMPLATES_DIR),
)
logger = logging.getLogger(__name__)


# Live roster: Eve speaks Vett's F5 clone, Kernel speaks Scotty's.
SUPPORTED_AGENTS: tuple[str, ...] = ("aetheria", "eve", "kernel")


def _voice_state() -> dict:
    """Access the voice state dict registered on the app at boot.

    Returns an empty dict if voice was never wired (no ELEVENLABS_API_KEY).
    This shouldn't happen in practice — startup.py only registers this
    blueprint when at least one agent is voice-configured — but defensive
    None handling keeps the route shape honest.
    """
    soveryn = current_app.extensions.get("soveryn", {}) or {}
    return soveryn.get("voice", {}) or {}


@bp.get("/voice")
def voice_landing():
    """Agent picker landing page. Lists the agents with voice configured.

    Agents not in voice_state are silently omitted.
    """
    state = _voice_state()
    available = [agent for agent in SUPPORTED_AGENTS if agent in state]
    return render_template("voice_landing.html", agents=available)


@bp.get("/voice/<agent>")
def voice_room(agent: str):
    """Per-agent voice room page (orb UI)."""
    agent = agent.lower().strip()
    if agent not in SUPPORTED_AGENTS:
        abort(404, description=f"voice not configured for agent {agent!r}")
    if agent not in _voice_state():
        abort(503, description=f"voice for {agent!r} not initialized "
                               "(missing ELEVENLABS_API_KEY?)")
    return render_template("voice.html", agent=agent)


@bp.post("/voice/<agent>/offer")
def voice_offer(agent: str):
    """WebRTC SDP offer endpoint — browser sends offer, we return answer.

    Each call spins up a SmallWebRTCConnection, negotiates the SDP
    answer, then schedules the T4 Pipecat pipeline as a background task
    that runs for the lifetime of the call. The HTTP response carries
    only the SDP answer (sdp/type/pc_id); audio flows over WebRTC
    directly between browser and the Pipecat transport.
    """
    agent = agent.lower().strip()
    if agent not in SUPPORTED_AGENTS:
        abort(404, description=f"voice not configured for agent {agent!r}")
    state = _voice_state().get(agent)
    if state is None:
        abort(503, description=f"voice for {agent!r} not initialized")

    body = request.get_json(silent=True) or {}
    sdp = body.get("sdp")
    sdp_type = body.get("type", "offer")
    if not isinstance(sdp, str) or not sdp.strip():
        return jsonify({"error": {
            "code": "missing_sdp",
            "message": "sdp field required",
        }}), 400
    if not isinstance(sdp_type, str) or not sdp_type.strip():
        return jsonify({"error": {
            "code": "missing_sdp_type",
            "message": "type field required",
        }}), 400

    # conv_store + agent_loop are pulled from the same app.extensions
    # dict; voice_state references them by name so we never duplicate
    # the long-lived singletons.
    conv_store = current_app.extensions["soveryn"]["conv_store"]
    agent_loop = state["agent_loop"]

    try:
        # session_id=None preserves the existing /voice/<agent> behavior:
        # mint a fresh session per call. The messenger voice route (Task 2)
        # passes the thread's existing session_id instead.
        answer = negotiate_and_dispatch_voice(
            agent_name=agent,
            agent_loop=agent_loop,
            conv_store=conv_store,
            voice_id=state["voice_id"],
            elevenlabs_api_key=state["elevenlabs_api_key"],
            parakeet_url=state.get("parakeet_url", "http://127.0.0.1:8087"),
            sdp=sdp,
            sdp_type=sdp_type,
            session_id=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("voice signaling failed for agent=%s", agent)
        return jsonify({"error": {
            "code": "signaling_failed",
            "message": f"{type(exc).__name__}: {exc}",
        }}), 500

    return jsonify(answer)


@bp.get("/voice/agents")
def voice_agents_list():
    """Which agents have voice configured. Localhost-only (mirror the /chat
    cookie-less surface). The messenger has its own auth-gated variant at
    ``GET /m/voice/agents`` for the PWA. Same payload shape so client code
    in both surfaces can share a parser."""
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        abort(403, description="voice/agents requires localhost")
    return jsonify({"agents": sorted(_voice_state().keys())})


@bp.post("/voice/session/<session_id>/offer")
def voice_session_offer(session_id: str):
    """WebRTC offer that binds the call to an EXISTING session_id (the
    desktop /chat surface uses this so voice turns land in the same
    conversation as text). Localhost-gated for the same reason — the
    /chat UI itself isn't auth-walled, and the funnel only exposes /m.

    Body: {"sdp", "type", "agent"}. Agent must match an agent in
    voice_state (i.e. has F5-TTS or ElevenLabs configured)."""
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        abort(403, description="voice/session requires localhost")

    body = request.get_json(silent=True) or {}
    sdp = body.get("sdp")
    sdp_type = body.get("type", "offer")
    agent = (body.get("agent") or "").lower().strip()

    if agent not in SUPPORTED_AGENTS:
        return jsonify({"error": f"unknown agent {agent!r}"}), 400
    state = _voice_state().get(agent)
    if state is None:
        return jsonify({
            "error": f"voice for {agent!r} not initialized",
        }), 503
    if not isinstance(sdp, str) or not sdp.strip():
        return jsonify({"error": "sdp field required"}), 400

    conv_store = current_app.extensions["soveryn"]["conv_store"]
    agent_loop = state["agent_loop"]

    try:
        answer = negotiate_and_dispatch_voice(
            agent_name=agent,
            agent_loop=agent_loop,
            conv_store=conv_store,
            voice_id=state["voice_id"],
            elevenlabs_api_key=state["elevenlabs_api_key"],
            parakeet_url=state.get("parakeet_url", "http://127.0.0.1:8087"),
            sdp=sdp,
            sdp_type=sdp_type,
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "voice/session offer failed agent=%s session=%s",
            agent, session_id,
        )
        return jsonify({"error": f"signaling failed: {type(exc).__name__}: {exc}"}), 500

    return jsonify(answer)



@bp.post("/voice/transcribe")
def voice_transcribe():
    """Proxy composer-mic audio to local Parakeet STT.

    The duplex call path (WebRTC + Pipecat) already uses Parakeet on
    127.0.0.1:8087. Messages thread dictation for agents without an F5
    clone (Eve, Kernel) hits the same service so we do not invent a TTS
    engine — just expose the existing /transcribe wire to the composer.
    """
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        abort(403, description="voice/transcribe requires localhost")
    audio = request.get_data() or b""
    if not audio:
        return jsonify({"error": "empty audio"}), 400
    import os
    import urllib.error
    import urllib.request

    parakeet = (
        os.environ.get("SOVERYN_PARAKEET_URL") or "http://127.0.0.1:8087"
    ).rstrip("/")
    req = urllib.request.Request(
        parakeet + "/transcribe",
        data=audio,
        method="POST",
        headers={
            "Content-Type": request.content_type or "application/octet-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
            return current_app.response_class(
                body, mimetype="application/json", status=resp.status
            )
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")[:400]
        logger.exception("parakeet transcribe HTTP %s", exc.code)
        return jsonify({"error": f"stt HTTP {exc.code}: {err_body}"}), 502
    except Exception as exc:  # noqa: BLE001
        logger.exception("parakeet transcribe failed")
        return jsonify({"error": f"stt failed: {type(exc).__name__}: {exc}"}), 502


__all__ = ["bp", "SUPPORTED_AGENTS"]
