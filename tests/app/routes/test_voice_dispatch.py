"""Tests for the shared voice dispatch helper.

Task 1 of the messenger voice integration plan extracts the body of
``voice.py::_negotiate_and_dispatch`` into
``voice_dispatch.negotiate_and_dispatch_voice`` so the messenger route
(Task 2) can pass an existing thread's ``session_id`` instead of minting
a fresh one per call.

These tests pin the two-branch contract:

  - When ``session_id`` is supplied, the helper uses it verbatim and
    never touches ``conv_store.new_session``. The dispatched pipeline
    runner receives that exact session_id.
  - When ``session_id=None``, the helper mints a new session via
    ``conv_store.new_session(agent_name, title="[voice] ...")`` —
    preserving the existing /voice/<agent> behavior byte-identically.

The function spawns a daemon thread that owns a fresh asyncio loop;
the captured pipeline kwargs populate asynchronously after ``init_done``
fires, so the assertions poll briefly to let the runner reach the
``run_aetheria_voice_session`` call. Both pipecat's
``SmallWebRTCConnection`` and the pipeline factory are monkeypatched at
their late-import paths so the test never touches real WebRTC, aiortc,
or onnxruntime.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest


# ─── Fakes ────────────────────────────────────────────────────────────────────


class _FakeWebRTCConnection:
    """Stands in for pipecat.transports.smallwebrtc.connection.SmallWebRTCConnection.

    ``initialize`` is an async no-op; ``get_answer`` returns a static SDP
    answer dict so the helper's ``answer_holder`` is non-empty and the
    Flask view path returns success. ``cleanup`` is async and trivial.
    """

    def __init__(self, *, ice_servers=None):
        self.ice_servers = ice_servers
        self.initialized_with: dict[str, Any] = {}

    async def initialize(self, *, sdp: str, type: str) -> None:  # noqa: A002
        self.initialized_with = {"sdp": sdp, "type": type}

    def get_answer(self) -> dict:
        return {"sdp": "v=0\r\nfake-answer\r\n", "type": "answer", "pc_id": "fake-pc"}

    async def cleanup(self) -> None:
        return None


def _make_fake_pipeline_runner(capture: dict):
    """Build an ``async def run_aetheria_voice_session(...)`` that records
    the kwargs it was called with, then returns immediately so the worker
    thread finishes quickly."""

    async def _fake_run(**kwargs) -> None:
        capture.update(kwargs)

    return _fake_run


class _FakeConvStore:
    """Records new_session calls and returns deterministic session ids."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def new_session(self, *args, **kwargs) -> str:
        self.calls.append((args, kwargs))
        return "minted-session-id"


def _patch_dispatch(monkeypatch, pipeline_capture: dict) -> None:
    """Monkeypatch the two late-imported names at their *real* import paths.

    The dispatch function imports them inside the function body via
    ``from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection``
    and ``from soveryn.platform.voice.pipeline import run_aetheria_voice_session``,
    so we patch the source modules — not attributes on ``voice_dispatch``.
    """
    import sys
    import types

    # Build/patch the pipecat module path.
    pipecat_conn_mod = types.ModuleType(
        "pipecat.transports.smallwebrtc.connection"
    )
    pipecat_conn_mod.SmallWebRTCConnection = _FakeWebRTCConnection

    # Ensure parent packages exist so the `from ... import ...` resolves.
    for name in (
        "pipecat",
        "pipecat.transports",
        "pipecat.transports.smallwebrtc",
    ):
        if name not in sys.modules:
            monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(
        sys.modules,
        "pipecat.transports.smallwebrtc.connection",
        pipecat_conn_mod,
    )

    # Patch the pipeline runner module.
    pipeline_mod = types.ModuleType("soveryn.platform.voice.pipeline")
    pipeline_mod.run_aetheria_voice_session = _make_fake_pipeline_runner(
        pipeline_capture,
    )
    for name in (
        "soveryn",
        "soveryn.platform",
        "soveryn.platform.voice",
    ):
        if name not in sys.modules:
            monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(
        sys.modules,
        "soveryn.platform.voice.pipeline",
        pipeline_mod,
    )


def _wait_for(predicate, *, timeout: float = 2.0, interval: float = 0.02) -> bool:
    """Poll until ``predicate()`` is truthy or timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_dispatch_uses_given_session_id_when_provided(monkeypatch):
    """Given session_id stays verbatim; conv_store.new_session is never called.

    Mirrors the messenger voice path (Task 2) where a thread's existing
    session_id binds the WebRTC call to the same conversation history as
    the text exchange.
    """
    pipeline_capture: dict = {}
    _patch_dispatch(monkeypatch, pipeline_capture)

    from soveryn.app.routes.voice_dispatch import negotiate_and_dispatch_voice

    conv_store = _FakeConvStore()
    answer = negotiate_and_dispatch_voice(
        agent_name="aetheria",
        agent_loop=object(),
        conv_store=conv_store,
        voice_id="vid",
        elevenlabs_api_key="key",
        parakeet_url="http://127.0.0.1:8087",
        sdp="v=0\r\noffer\r\n",
        sdp_type="offer",
        session_id="existing-session-id",
    )

    # SDP answer round-trips.
    assert answer == {
        "sdp": "v=0\r\nfake-answer\r\n",
        "type": "answer",
        "pc_id": "fake-pc",
    }

    # conv_store.new_session must NOT have been called.
    assert conv_store.calls == [], (
        f"new_session called despite explicit session_id: {conv_store.calls}"
    )

    # The pipeline runner runs in a daemon thread after init_done fires.
    # Poll briefly for the captured session_id.
    ok = _wait_for(lambda: "session_id" in pipeline_capture)
    assert ok, (
        f"pipeline runner never captured kwargs within timeout; "
        f"capture={pipeline_capture}"
    )
    assert pipeline_capture["session_id"] == "existing-session-id"


def test_dispatch_mints_session_when_none(monkeypatch):
    """session_id=None preserves the original /voice/<agent> behavior:
    a fresh session is minted with title prefix '[voice] '."""
    pipeline_capture: dict = {}
    _patch_dispatch(monkeypatch, pipeline_capture)

    from soveryn.app.routes.voice_dispatch import negotiate_and_dispatch_voice

    conv_store = _FakeConvStore()
    negotiate_and_dispatch_voice(
        agent_name="aetheria",
        agent_loop=object(),
        conv_store=conv_store,
        voice_id="vid",
        elevenlabs_api_key="key",
        parakeet_url="http://127.0.0.1:8087",
        sdp="v=0\r\noffer\r\n",
        sdp_type="offer",
        session_id=None,
    )

    assert len(conv_store.calls) == 1, (
        f"expected exactly one new_session call, got {conv_store.calls}"
    )
    args, kwargs = conv_store.calls[0]
    assert args[0] == "aetheria", (
        f"first positional arg must be agent_name; got {args!r}"
    )
    assert "title" in kwargs, f"title kwarg missing: {kwargs!r}"
    assert kwargs["title"].startswith("[voice]"), (
        f"title kwarg should start with '[voice]'; got {kwargs['title']!r}"
    )

    # The pipeline runner should have been called with the minted id.
    ok = _wait_for(lambda: "session_id" in pipeline_capture)
    assert ok, (
        f"pipeline runner never captured kwargs within timeout; "
        f"capture={pipeline_capture}"
    )
    assert pipeline_capture["session_id"] == "minted-session-id"
