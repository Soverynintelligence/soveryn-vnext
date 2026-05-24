"""Tests for soveryn/app/routes/ui.py — vNext-native UI route."""

import json
import re
import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})


@pytest.fixture
def app_state(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()


def test_root_serves_vnext_native_ui(app_state):
    resp = app_state.get("/")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert resp.headers.get("X-SOVERYN-UI-Source") == "vnext-native"
    # Smoke: the page has a recognizable marker
    body = resp.data.decode("utf-8")
    assert "vNext" in body or "soveryn" in body.lower()


def test_root_no_external_resources_loaded(app_state):
    """No <script src="https://..."> or <link href="https://...">"""
    body = app_state.get("/").data.decode("utf-8")
    external_scripts = re.findall(r'<script[^>]+src=["\']https?://', body)
    external_styles = re.findall(r'<link[^>]+href=["\']https?://', body)
    assert external_scripts == [], f"external scripts found: {external_scripts}"
    assert external_styles == [], f"external stylesheets found: {external_styles}"


def test_root_uses_no_hardcoded_agents(app_state):
    """The page must NOT list scout/vision/ares/tinker. Agent list is fetched
    from /api/models at runtime."""
    body = app_state.get("/").data.decode("utf-8").lower()
    # Agent NAMES that must not appear as hardcoded UI labels
    forbidden = ["scout", "vision", "tinker", "ares_llm", "aetheria_public"]
    for name in forbidden:
        assert name not in body, f"hardcoded retired agent name {name!r} in UI"


def test_root_uses_no_hardcoded_gpu_labels(app_state):
    """The page must NOT carry hardcoded GPU labels (Blackwell, RTX 8000, GPU 0/1/2)."""
    body = app_state.get("/").data.decode("utf-8").lower()
    forbidden = ["blackwell", "rtx 8000", "rtx pro 5000", "quadro"]
    for label in forbidden:
        assert label not in body, f"hardcoded GPU label {label!r} in UI"


def test_legacy_moved_to_legacy_path(app_state):
    """The legacy bridge moved from / to /legacy."""
    resp = app_state.get("/legacy")
    # In the test fixture the default legacy_templates_dir points at production,
    # which DOES exist in the dev environment — the response should be 200 OR 503
    # (503 if the dev environment doesn't have it). Either is OK; what matters
    # is that /legacy ROUTES to ui_compat, not 404.
    assert resp.status_code in (200, 503)
    if resp.status_code == 503:
        body = json.loads(resp.data)
        assert body["error"]["code"] == "ui_unavailable"


def test_legacy_mobile_moved_to_legacy_path(app_state):
    resp = app_state.get("/legacy/mobile")
    assert resp.status_code in (200, 503)


def test_old_root_no_longer_serves_legacy_template(app_state):
    """GET / serves vNext UI, NOT the legacy desktop_v2.html."""
    resp = app_state.get("/")
    body = resp.data.decode("utf-8")
    # Legacy template had this signature drawer button text
    assert "Tinker" not in body
    assert "Vision" not in body
    assert "Scout" not in body
    # And no X-SOVERYN-UI-Source: legacy-template
    assert resp.headers.get("X-SOVERYN-UI-Source") == "vnext-native"


def test_ui_source_metadata_still_works(app_state):
    """/ui/source still reports legacy bridge metadata for the moved paths."""
    resp = app_state.get("/ui/source")
    assert resp.status_code == 200
