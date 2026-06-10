"""Tests for soveryn/app/routes/ui_compat.py — legacy template bridge.

Uses tmp_path for the legacy dir; NEVER points at the real production
soveryn_complete/templates path.
"""

import json
import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.routes.ui_compat import LEGACY_SOURCE_HEADER, LEGACY_SOURCE_VALUE
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})


@pytest.fixture
def legacy_dir(tmp_path):
    """Build a fake legacy templates dir with both expected files."""
    d = tmp_path / "legacy_templates"
    d.mkdir()
    (d / "desktop_v2.html").write_text("<html><body>desktop-legacy</body></html>",
                                        encoding="utf-8")
    (d / "mobile_v3.html").write_text("<html><body>mobile-legacy</body></html>",
                                       encoding="utf-8")
    return d


@pytest.fixture
def app_state(tmp_path, fake_chat, legacy_dir):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    app.config["SOVERYN_LEGACY_TEMPLATES_DIR"] = str(legacy_dir)
    return app.test_client()


def _err(resp):
    return json.loads(resp.data)["error"]


# ─── GET /legacy (desktop) ───────────────────────────────────────────────────

def test_legacy_serves_legacy_desktop_html(app_state):
    resp = app_state.get("/legacy")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert b"desktop-legacy" in resp.data


def test_legacy_sets_legacy_source_header(app_state):
    resp = app_state.get("/legacy")
    assert resp.headers.get(LEGACY_SOURCE_HEADER) == LEGACY_SOURCE_VALUE


# ─── GET /legacy/mobile ──────────────────────────────────────────────────────

def test_legacy_mobile_serves_legacy_mobile_html(app_state):
    resp = app_state.get("/legacy/mobile")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert b"mobile-legacy" in resp.data


def test_legacy_mobile_sets_legacy_source_header(app_state):
    resp = app_state.get("/legacy/mobile")
    assert resp.headers.get(LEGACY_SOURCE_HEADER) == LEGACY_SOURCE_VALUE


# ─── Missing files → 503 JSON, NOT stack trace ───────────────────────────────

def test_legacy_503_when_desktop_template_missing(tmp_path, fake_chat):
    """No desktop_v2.html in the legacy dir → 503 JSON, not a 500 stack trace."""
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    empty_dir = tmp_path / "empty_legacy"
    empty_dir.mkdir()
    app.config["SOVERYN_LEGACY_TEMPLATES_DIR"] = str(empty_dir)
    resp = app.test_client().get("/legacy")
    assert resp.status_code == 503
    assert resp.content_type.startswith("application/json")
    assert _err(resp)["code"] == "ui_unavailable"
    # Header is NOT set on the error response
    assert resp.headers.get(LEGACY_SOURCE_HEADER) is None


def test_legacy_mobile_503_when_mobile_template_missing(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    partial_dir = tmp_path / "partial_legacy"
    partial_dir.mkdir()
    # Only desktop exists, not mobile
    (partial_dir / "desktop_v2.html").write_text("<html></html>")
    app.config["SOVERYN_LEGACY_TEMPLATES_DIR"] = str(partial_dir)
    client = app.test_client()
    assert client.get("/legacy").status_code == 200  # desktop works
    resp = client.get("/legacy/mobile")
    assert resp.status_code == 503
    assert _err(resp)["code"] == "ui_unavailable"


def test_legacy_503_when_legacy_dir_does_not_exist(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    app.config["SOVERYN_LEGACY_TEMPLATES_DIR"] = str(tmp_path / "does_not_exist")
    resp = app.test_client().get("/legacy")
    assert resp.status_code == 503
    assert _err(resp)["code"] == "ui_unavailable"


# ─── GET /ui/source — metadata ───────────────────────────────────────────────

def test_ui_source_reports_temporary_flag(app_state):
    resp = app_state.get("/ui/source")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["_temporary"] is True
    assert "TODO(vnext-ui)" in payload["_note"]


def test_ui_source_reports_template_existence(app_state, legacy_dir):
    resp = app_state.get("/ui/source")
    payload = json.loads(resp.data)
    assert payload["legacy_templates_dir"] == str(legacy_dir)
    assert payload["templates"]["desktop"]["exists"] is True
    assert payload["templates"]["mobile"]["exists"] is True


def test_ui_source_reports_missing_templates_correctly(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    empty = tmp_path / "empty"
    empty.mkdir()
    app.config["SOVERYN_LEGACY_TEMPLATES_DIR"] = str(empty)
    payload = json.loads(app.test_client().get("/ui/source").data)
    assert payload["templates"]["desktop"]["exists"] is False
    assert payload["templates"]["mobile"]["exists"] is False


# ─── Default config value ────────────────────────────────────────────────────

def test_default_legacy_templates_dir_is_production_path(tmp_path, fake_chat):
    """create_app sets a sensible default pointing at the vnext templates_legacy dir.

    Updated for path-consolidation T4 (2026-06-10): default now derives from
    Path.home() and lives under ~/soveryn_vnext/data/templates_legacy, not
    the soveryn_complete museum.
    """
    from pathlib import Path
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    expected = str(Path.home() / "soveryn_vnext" / "data" / "templates_legacy")
    assert app.config["SOVERYN_LEGACY_TEMPLATES_DIR"] == expected


# ─── No static asset proxy — constraint 7 ────────────────────────────────────

def test_static_paths_not_served_by_bridge(app_state):
    """Bridge serves HTML only; /static/foo.js gets clean 404 from Flask."""
    resp = app_state.get("/static/some_asset.js")
    assert resp.status_code == 404
    # Comes through the global JSON error envelope
    assert _err(resp)["code"] == "not_found"
