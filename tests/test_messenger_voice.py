"""Tests for the messenger voice routes (Voice T2 + T3).

  - GET  /m/voice/agents              — capability surface for the PWA
  - POST /m/threads/<tid>/voice/offer — WebRTC offer bound to thread session

The /voice/agents route lets the PWA gate the call button on per-agent
voice availability (Phase 1: only Aetheria has a voice character; Vett
and Scotty don't until theirs are sourced). The /voice/offer route binds
the WebRTC call to the thread's existing session_id so transcribed turns
land in the same ConversationStore history as the text exchange — Aetheria
remembers voice and text as one conversation, not two parallel ones.

The voice_state shape these tests register on ``app.extensions["soveryn"]``
matches what startup.py builds for the standalone /voice/<agent>/offer
route — same keys, same fallbacks. PWA + voice route share that contract.
"""
from __future__ import annotations

import pytest
from flask import Flask

from soveryn.app.routes.messenger import build_messenger_blueprint
from soveryn.app.messenger.store import MessengerStore
from soveryn.memory.conversation_store import ConversationStore


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def stores(tmp_path):
    return (
        MessengerStore(tmp_path / "m.db"),
        ConversationStore(tmp_path / "conv.db"),
    )


@pytest.fixture
def app_no_voice(stores):
    """Flask app with messenger blueprint + no voice extension at all.

    Mirrors the runtime case where ELEVENLABS_API_KEY was unset at boot
    and startup.py never registered the voice blueprint or voice_state.
    """
    messenger_store, conv_store = stores
    flask_app = Flask(__name__)
    bp = build_messenger_blueprint(
        messenger_store=messenger_store,
        conv_store=conv_store,
        agent_loops={"aetheria": object(), "vett": object()},
    )
    flask_app.register_blueprint(bp)
    flask_app.config["TESTING"] = True
    flask_app._messenger_store = messenger_store
    flask_app._conv_store = conv_store
    return flask_app


@pytest.fixture
def app_with_voice(stores):
    """Flask app with voice configured for Aetheria only — Phase 1 reality.

    voice_state shape mirrors what startup.py builds for the standalone
    /voice/<agent>/offer route. PWA + voice routes share this contract:

        app.extensions["soveryn"]["voice"][agent_name] = {
            "voice_id": str,
            "elevenlabs_api_key": str,
            "parakeet_url": str,      # optional; defaults to 127.0.0.1:8087
            "agent_loop": AgentLoop,  # the long-lived singleton
        }
    """
    messenger_store, conv_store = stores
    flask_app = Flask(__name__)
    bp = build_messenger_blueprint(
        messenger_store=messenger_store,
        conv_store=conv_store,
        agent_loops={"aetheria": object(), "vett": object()},
    )
    flask_app.register_blueprint(bp)
    flask_app.config["TESTING"] = True
    flask_app.extensions.setdefault("soveryn", {})
    flask_app.extensions["soveryn"]["conv_store"] = conv_store
    flask_app.extensions["soveryn"]["voice"] = {
        "aetheria": {
            "voice_id": "vid-aetheria",
            "elevenlabs_api_key": "test-key",
            "parakeet_url": "http://127.0.0.1:8087",
            "agent_loop": object(),
        },
    }
    flask_app._messenger_store = messenger_store
    flask_app._conv_store = conv_store
    return flask_app


def _pair_and_get_secret(client):
    mint = client.post(
        "/m/pair", json={"label": "phone"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    code = mint.get_json()["code"]
    claim = client.post(f"/m/pair/{code}", json={"device_label": "Pixel 9"})
    return claim.get_json()["secret"]


def _create_thread(client, secret, agent):
    resp = client.post(
        "/m/threads", json={"agent": agent},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()["thread_id"]


# ─── GET /m/voice/agents ─────────────────────────────────────────────────────


def test_voice_agents_returns_voice_state_keys(app_with_voice):
    client = app_with_voice.test_client()
    secret = _pair_and_get_secret(client)

    resp = client.get(
        "/m/voice/agents",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"agents": ["aetheria"]}


def test_voice_agents_empty_when_voice_unconfigured(app_no_voice):
    """No voice extension registered at all → PWA hides the call button."""
    client = app_no_voice.test_client()
    secret = _pair_and_get_secret(client)

    resp = client.get(
        "/m/voice/agents",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"agents": []}


def test_voice_agents_requires_auth(app_with_voice):
    client = app_with_voice.test_client()
    resp = client.get("/m/voice/agents")
    assert resp.status_code == 401


# ─── POST /m/threads/<tid>/voice/offer ───────────────────────────────────────


def test_voice_offer_passes_thread_session_id(app_with_voice, monkeypatch):
    """The critical correctness check: the dispatch helper must receive
    the thread's existing session_id verbatim, NOT None — otherwise the
    voice call would mint a fresh session and transcribed turns would
    land in a parallel history.
    """
    captured: dict = {}

    def _fake_dispatch(**kwargs):
        captured.update(kwargs)
        return {
            "sdp": "v=0\r\nfake-answer\r\n",
            "type": "answer",
            "pc_id": "fake-pc-1",
        }

    # Patch at the import path the messenger route uses (late import
    # inside the function body, so we patch the source module).
    import soveryn.app.routes.voice_dispatch as vd_mod
    monkeypatch.setattr(vd_mod, "negotiate_and_dispatch_voice", _fake_dispatch)

    client = app_with_voice.test_client()
    secret = _pair_and_get_secret(client)
    tid = _create_thread(client, secret, "aetheria")

    # Pull the real session_id the thread was bound to.
    from soveryn.app.messenger.threads import get_thread
    thread = get_thread(app_with_voice._messenger_store, thread_id=tid)
    assert thread is not None
    expected_session_id = thread.session_id

    resp = client.post(
        f"/m/threads/{tid}/voice/offer",
        json={"sdp": "v=0\r\noffer\r\n", "type": "offer"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    answer = resp.get_json()
    assert answer["pc_id"] == "fake-pc-1"

    # The load-bearing assertion: the existing session_id flows through.
    assert captured["session_id"] == expected_session_id, (
        f"voice route minted/mangled session_id; expected "
        f"{expected_session_id!r}, got {captured.get('session_id')!r}"
    )
    assert captured["agent_name"] == "aetheria"
    # Sanity: the per-agent voice_state values were unpacked correctly.
    assert captured["voice_id"] == "vid-aetheria"
    assert captured["elevenlabs_api_key"] == "test-key"
    assert captured["parakeet_url"] == "http://127.0.0.1:8087"
    assert captured["sdp"] == "v=0\r\noffer\r\n"
    assert captured["sdp_type"] == "offer"


def test_voice_offer_503_when_agent_no_voice(app_with_voice):
    """Vett has no voice character in Phase 1 → 503 with agent name."""
    client = app_with_voice.test_client()
    secret = _pair_and_get_secret(client)
    tid = _create_thread(client, secret, "vett")

    resp = client.post(
        f"/m/threads/{tid}/voice/offer",
        json={"sdp": "v=0\r\noffer\r\n", "type": "offer"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 503
    body = resp.get_json()
    assert "vett" in body["error"].lower()


def test_voice_offer_404_unknown_thread(app_with_voice):
    client = app_with_voice.test_client()
    secret = _pair_and_get_secret(client)

    resp = client.post(
        "/m/threads/does-not-exist/voice/offer",
        json={"sdp": "v=0\r\noffer\r\n", "type": "offer"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 404


def test_voice_offer_400_missing_sdp(app_with_voice):
    """Mirrors the standalone voice.py validation — empty/missing sdp → 400."""
    client = app_with_voice.test_client()
    secret = _pair_and_get_secret(client)
    tid = _create_thread(client, secret, "aetheria")

    resp = client.post(
        f"/m/threads/{tid}/voice/offer",
        json={},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 400

    resp = client.post(
        f"/m/threads/{tid}/voice/offer",
        json={"sdp": "   "},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 400


def test_voice_offer_requires_auth(app_with_voice):
    """Belt-and-braces: voice offer route must be auth-gated."""
    client = app_with_voice.test_client()
    resp = client.post(
        "/m/threads/whatever/voice/offer",
        json={"sdp": "v=0\r\noffer\r\n"},
    )
    assert resp.status_code == 401


def test_voice_offer_touches_thread(app_with_voice, monkeypatch):
    """Successful dispatch must call touch_thread so the thread bubbles
    to the top of the PWA list."""
    def _fake_dispatch(**kwargs):
        return {"sdp": "v=0\r\nfake\r\n", "type": "answer", "pc_id": "x"}

    import soveryn.app.routes.voice_dispatch as vd_mod
    monkeypatch.setattr(vd_mod, "negotiate_and_dispatch_voice", _fake_dispatch)

    client = app_with_voice.test_client()
    secret = _pair_and_get_secret(client)
    tid = _create_thread(client, secret, "aetheria")

    from soveryn.app.messenger.threads import get_thread
    before = get_thread(app_with_voice._messenger_store, thread_id=tid)

    # Sleep-free: touch_thread's last_activity uses a UTC isoformat string.
    # If our route doesn't call it, the value won't change on the second
    # read after the POST. (We could also just import touch_thread and
    # monkeypatch it to record the call, which is what we do here.)
    touched: list = []
    import soveryn.app.routes.messenger as messenger_mod
    real_touch = messenger_mod.touch_thread

    def _spy_touch(store, *, thread_id):
        touched.append(thread_id)
        return real_touch(store, thread_id=thread_id)

    monkeypatch.setattr(messenger_mod, "touch_thread", _spy_touch)

    resp = client.post(
        f"/m/threads/{tid}/voice/offer",
        json={"sdp": "v=0\r\noffer\r\n", "type": "offer"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    assert touched == [tid], (
        f"touch_thread was not called with the right tid; touched={touched}"
    )
    assert before is not None  # silence unused; kept for diagnostic readability
