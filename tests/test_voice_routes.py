"""Tests for Task 5 of the Sovereign Voice Phase 1 plan: Flask blueprint.

Covers:
  - /voice landing renders when voice is enabled, with Aetheria visible.
  - /voice/aetheria renders the orb room stub.
  - /voice/<unknown agent> returns 404.
  - /voice routes are NOT registered when ELEVENLABS_API_KEY is missing.
  - /voice/<agent>/offer rejects missing SDP / unknown agents / unconfigured agents.

WebRTC round-trip is NOT exercised here — that needs a real browser, see
Task 8 (live verification). These tests verify routing + error handling
only.

Path discipline mirrors tests/test_continuity_startup_wiring.py: tmp_path
fixtures for souls/pinned/recall, monkeypatch for env vars.
"""

from __future__ import annotations
from pathlib import Path

import pytest

from soveryn.app.startup import create_app
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fake_souls_dir(tmp_path) -> Path:
    souls_dir = tmp_path / "souls"
    souls_dir.mkdir()
    (souls_dir / "aetheria.md").write_text("# Aetheria\n", encoding="utf-8")
    (souls_dir / "kernel.md").write_text("# Kernel\n", encoding="utf-8")
    (souls_dir / "eve.md").write_text("# Eve\n", encoding="utf-8")
    return souls_dir


@pytest.fixture
def fake_pinned(tmp_path) -> Path:
    pinned = tmp_path / "pinned.md"
    pinned.write_text("# Pinned\n", encoding="utf-8")
    return pinned


@pytest.fixture
def recall_lattice_path(tmp_path) -> Path:
    store = LatticeStore(tmp_path / "recall_lattice.db")
    store.write_node(
        "aetheria",
        "voice routes test fixture memory",
        provenance={
            "cls": "witnessed",
            "source": "test",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    return tmp_path / "recall_lattice.db"


def _configure_env(
    monkeypatch,
    *,
    fake_souls_dir: Path,
    fake_pinned: Path,
    recall_lattice_path: Path,
) -> None:
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(recall_lattice_path))
    monkeypatch.setenv("SOVERYN_LATTICE_DB", str(recall_lattice_path))


@pytest.fixture
def app_with_voice(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    """Boot create_app() with ELEVENLABS_* set so the voice blueprint registers."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID_AETHERIA", "test-voice-id")
    _configure_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice_path=recall_lattice_path,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    app.config["TESTING"] = True
    return app


@pytest.fixture
def app_without_voice(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    """Boot create_app() with voice genuinely disabled.

    Phase 2 (F5-TTS): dropping ELEVENLABS_API_KEY alone is no longer enough to
    disable voice — F5-TTS is the default primary and doesn't need ElevenLabs
    creds.  To force the no-voice path we must ALSO set SOVEREIGN_TTS_PRIMARY
    to 'elevenlabs', which makes the ElevenLabs key + voice_id both mandatory;
    with neither present, voice_state stays empty and the blueprint is skipped.
    """
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID_AETHERIA", raising=False)
    monkeypatch.setenv("SOVEREIGN_TTS_PRIMARY", "elevenlabs")
    _configure_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice_path=recall_lattice_path,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    app.config["TESTING"] = True
    return app


# ─── /voice landing ──────────────────────────────────────────────────────────


def test_voice_landing_renders_when_voice_enabled(app_with_voice):
    client = app_with_voice.test_client()
    rv = client.get("/voice")
    assert rv.status_code == 200
    assert b"aetheria" in rv.data.lower()


def test_voice_routes_not_registered_when_voice_disabled(app_without_voice):
    """No ELEVENLABS_API_KEY → /voice returns 404 (no route registered)."""
    client = app_without_voice.test_client()
    rv = client.get("/voice")
    assert rv.status_code == 404


# ─── /voice/<agent> room ─────────────────────────────────────────────────────


def test_voice_aetheria_room_renders(app_with_voice):
    client = app_with_voice.test_client()
    rv = client.get("/voice/aetheria")
    assert rv.status_code == 200
    # voice.html has <div id="orb" ...> — verifying the stub renders
    assert b"orb" in rv.data.lower()
    assert b"aetheria" in rv.data.lower()


def test_voice_unconfigured_agent_404(app_with_voice):
    """Agents not in SUPPORTED_AGENTS (aetheria/vett/scotty) get 404.
    Phase 2 (F5-TTS): vett and scotty are now supported; use 'ares' instead."""
    client = app_with_voice.test_client()
    rv = client.get("/voice/ares")
    assert rv.status_code == 404


def test_voice_specialist_or_daemon_404(app_with_voice):
    """Phase 1 surfaces only aetheria; specialists / daemons stay invisible."""
    client = app_with_voice.test_client()
    rv = client.get("/voice/heartbeat")
    assert rv.status_code == 404


# ─── /voice/<agent>/offer signaling errors ───────────────────────────────────


def test_voice_offer_rejects_missing_sdp(app_with_voice):
    client = app_with_voice.test_client()
    rv = client.post("/voice/aetheria/offer", json={})
    assert rv.status_code == 400
    assert b"missing_sdp" in rv.data


def test_voice_offer_rejects_empty_sdp_string(app_with_voice):
    client = app_with_voice.test_client()
    rv = client.post(
        "/voice/aetheria/offer",
        json={"sdp": "   ", "type": "offer"},
    )
    assert rv.status_code == 400
    assert b"missing_sdp" in rv.data


def test_voice_offer_rejects_unknown_agent(app_with_voice):
    """POST /voice/<unknown>/offer for an agent not in SUPPORTED_AGENTS returns 404.
    Phase 2 (F5-TTS): scotty is now supported; use 'nobody' instead."""
    client = app_with_voice.test_client()
    rv = client.post(
        "/voice/nobody/offer",
        json={"sdp": "v=0\r\n", "type": "offer"},
    )
    assert rv.status_code == 404


def test_voice_offer_uninitialized_agent_503(app_with_voice):
    """If SUPPORTED_AGENTS contains an agent but voice_state doesn't have
    it (misconfiguration), 503 — distinguishable from the 404 unknown-agent
    case."""
    state = app_with_voice.extensions["soveryn"]["voice"]
    state.pop("aetheria", None)
    client = app_with_voice.test_client()
    rv = client.post(
        "/voice/aetheria/offer",
        json={"sdp": "v=0\r\n", "type": "offer"},
    )
    assert rv.status_code == 503
