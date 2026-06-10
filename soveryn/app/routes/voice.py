"""Voice blueprint — /voice landing + /voice/<agent> per-agent voice room.

Aetheria-only in Phase 1. SUPPORTED_AGENTS extends to include vett +
scotty in Phase 1.5 once their voice characters are sourced.

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

import asyncio
import logging
import threading
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
)


_THIS_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _THIS_DIR.parent / "templates"
_STATIC_DIR = _THIS_DIR.parent / "static"


bp = Blueprint(
    "voice",
    __name__,
    template_folder=str(_TEMPLATES_DIR),
    static_folder=str(_STATIC_DIR),
    static_url_path="/static",
)
logger = logging.getLogger(__name__)


# Phase 1: Aetheria only. Phase 1.5 grows this tuple to ("aetheria",
# "vett", "scotty") once their voice characters are sourced.
SUPPORTED_AGENTS: tuple[str, ...] = ("aetheria",)


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

    Phase 1: only Aetheria. Phase 1.5 adds Vett + Scotty as their voice
    characters land. Agents not in voice_state are silently omitted.
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
        answer = _negotiate_and_dispatch(
            agent_name=agent,
            agent_loop=agent_loop,
            conv_store=conv_store,
            voice_id=state["voice_id"],
            elevenlabs_api_key=state["elevenlabs_api_key"],
            parakeet_url=state.get("parakeet_url", "http://127.0.0.1:8087"),
            sdp=sdp,
            sdp_type=sdp_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("voice signaling failed for agent=%s", agent)
        return jsonify({"error": {
            "code": "signaling_failed",
            "message": f"{type(exc).__name__}: {exc}",
        }}), 500

    return jsonify(answer)


def _negotiate_and_dispatch(
    *,
    agent_name: str,
    agent_loop,
    conv_store,
    voice_id: str,
    elevenlabs_api_key: str,
    parakeet_url: str,
    sdp: str,
    sdp_type: str,
) -> dict:
    """Drive Pipecat signaling + spawn the pipeline runner.

    Returns the SDP answer dict ({sdp, type, pc_id}) for the browser.

    The pipeline runs as a long-lived asyncio task on a dedicated
    background event loop (one loop per session) so the Flask request
    can complete cleanly while the WebRTC audio path stays open. The
    loop is owned by the session and cleaned up by the pipeline's
    on_client_disconnected handler in T4's factory.
    """
    # Late import so module import doesn't pull aiortc/onnx into every
    # Flask process — Pipecat is heavy. The route module stays cheap to
    # import; the cost only lands when a voice call actually starts.
    from pipecat.transports.smallwebrtc.connection import (
        SmallWebRTCConnection,
    )
    from soveryn.platform.voice.pipeline import run_aetheria_voice_session

    # Mint a fresh session for this call. Title prefix [voice] per the
    # spec — keeps voice exchanges out of the autonomous-prefix set
    # while letting Cross-Surface Continuity pick them up.
    session_id = conv_store.new_session(
        agent_name, title=f"[voice] {agent_name}",
    )

    # Build the connection. ICE servers default to a public STUN; for
    # localhost-only Phase 1 this is harmless and lets the browser
    # gather host candidates without complaint.
    connection = SmallWebRTCConnection(
        ice_servers=["stun:stun.l.google.com:19302"],
    )

    # Initialize is async. We drive it on a fresh background event loop
    # so the synchronous Flask view can wait for the answer without
    # blocking on a loop the rest of the app might own. The same loop
    # then runs the pipeline for the session's lifetime.
    answer_holder: dict = {}
    init_error: list[BaseException] = []
    init_done = threading.Event()

    def _run_session_loop() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(connection.initialize(sdp=sdp, type=sdp_type))
        except BaseException as exc:  # noqa: BLE001
            init_error.append(exc)
            init_done.set()
            loop.close()
            return

        try:
            answer_holder.update(connection.get_answer() or {})
        finally:
            init_done.set()

        # Now run the pipeline for the lifetime of the call. When the
        # client disconnects, T4's on_client_disconnected handler cancels
        # the worker and run() returns.
        try:
            loop.run_until_complete(run_aetheria_voice_session(
                webrtc_connection=connection,
                agent_loop=agent_loop,
                session_id=session_id,
                elevenlabs_api_key=elevenlabs_api_key,
                voice_id=voice_id,
                parakeet_url=parakeet_url,
            ))
        except Exception:
            logger.exception(
                "voice pipeline crashed for agent=%s session=%s",
                agent_name, session_id,
            )
        finally:
            try:
                loop.run_until_complete(connection.cleanup())
            except Exception:  # noqa: BLE001
                logger.exception("voice connection cleanup failed")
            loop.close()

    thread = threading.Thread(
        target=_run_session_loop,
        name=f"voice-{agent_name}-{session_id[:8]}",
        daemon=True,
    )
    thread.start()

    # Wait for initialize() to complete (or fail). Bound at 30s; any
    # longer and ICE/SDP negotiation isn't going to recover anyway.
    if not init_done.wait(timeout=30.0):
        raise TimeoutError("WebRTC initialize() timed out after 30s")
    if init_error:
        raise init_error[0]
    if not answer_holder:
        raise RuntimeError("WebRTC connection produced no answer")

    return answer_holder


__all__ = ["bp", "SUPPORTED_AGENTS"]
