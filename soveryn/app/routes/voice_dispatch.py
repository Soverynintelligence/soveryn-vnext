"""Shared voice signaling + pipeline dispatch.

Extracted from ``voice.py::_negotiate_and_dispatch`` so multiple routes can
drive the same Pipecat WebRTC signaling path. The original /voice/<agent>
flow mints a fresh session per call (``session_id=None``). The messenger
voice route binds the call to an existing thread's session_id so transcribed
turns land in the same conversation history as the text exchange.

The body of ``negotiate_and_dispatch_voice`` is a verbatim lift of the
original ``_negotiate_and_dispatch`` plus one early branch on ``session_id``.
Everything else — late imports of pipecat + the pipeline factory, the
dedicated background event loop per call, the 30s init bound — stays put.
"""

from __future__ import annotations

import asyncio
import logging
import threading


logger = logging.getLogger(__name__)


def negotiate_and_dispatch_voice(
    *,
    agent_name: str,
    agent_loop,
    conv_store,
    voice_id: str,
    elevenlabs_api_key: str,
    parakeet_url: str,
    sdp: str,
    sdp_type: str,
    session_id: str | None = None,
) -> dict:
    """Drive Pipecat signaling + spawn the pipeline runner.

    Returns the SDP answer dict ({sdp, type, pc_id}) for the browser.

    Args:
        session_id: When ``None`` (the /voice/<agent> path) a fresh session
            is minted via ``conv_store.new_session`` with a ``[voice]``
            title prefix. When provided (the messenger voice path) it is
            used verbatim — ``conv_store.new_session`` is NOT called, so
            transcribed turns land in the caller's existing thread history.

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

    # Mint a fresh session only when the caller didn't provide one. The
    # messenger voice route passes the thread's existing session_id so
    # transcribed turns join the same history as the text exchange.
    if session_id is None:
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


__all__ = ["negotiate_and_dispatch_voice"]
