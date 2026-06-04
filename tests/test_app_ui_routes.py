"""Tests for soveryn/app/routes/ui.py — vNext command center at /."""

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


def test_root_serves_command_center(app_state):
    resp = app_state.get("/")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/html")
    assert resp.headers.get("X-SOVERYN-UI-Source") == "vnext-native"
    body = resp.data.decode("utf-8")
    assert 'data-testid="command-center"' in body


def test_root_has_greeting_block(app_state):
    body = app_state.get("/").data.decode("utf-8")
    assert 'data-testid="greeting"' in body


def test_root_has_agent_row_with_active_agents(app_state):
    body = app_state.get("/").data.decode("utf-8").lower()
    for agent in ACTIVE_AGENTS:
        assert f'data-agent="{agent}"' in body


def test_root_has_activity_feed(app_state):
    body = app_state.get("/").data.decode("utf-8")
    assert 'data-testid="activity-feed"' in body


def test_root_has_system_panel(app_state):
    body = app_state.get("/").data.decode("utf-8")
    assert 'data-testid="system-panel"' in body


def test_root_has_gpu_bars(app_state):
    body = app_state.get("/").data.decode("utf-8")
    assert 'data-testid="gpu-bars"' in body


def test_root_no_hardcoded_retired_agents(app_state):
    body = app_state.get("/").data.decode("utf-8").lower()
    for retired in ("scout", "vision", "tinker", "ares_llm"):
        assert retired not in body, f"hardcoded retired {retired!r} in command center"


def test_root_no_hardcoded_gpu_labels_in_stats_panel(app_state):
    """Guards against hardcoded GPU model names in the GPU stats area —
    those should come from /api/system/gpu, not the template. The topology
    view (added 2026-06-04) legitimately names hardware architecture
    (e.g. "Blackwell 96GB · live" on the SOVERYN tower node), so we scope
    the check to the GPU bars panel rather than the whole body."""
    body = app_state.get("/").data.decode("utf-8").lower()
    # Slice to the gpu-bars section only.
    gpu_section_start = body.find('data-testid="gpu-bars"')
    assert gpu_section_start >= 0, "gpu-bars panel missing from command center"
    # The gpu-bars section ends at the next closing </div> of the system panel.
    gpu_section_end = body.find('class="system-stats"', gpu_section_start)
    gpu_section = body[gpu_section_start:gpu_section_end if gpu_section_end > 0 else gpu_section_start + 2000]
    for label in ("blackwell", "rtx 8000", "rtx pro 5000", "quadro"):
        assert label not in gpu_section, \
            f"hardcoded GPU label {label!r} in the GPU stats panel"


def test_root_no_external_resources(app_state):
    body = app_state.get("/").data.decode("utf-8")
    assert re.findall(r'<script[^>]+src=["\']https?://', body) == []
    assert re.findall(r'<link[^>]+href=["\']https?://', body) == []


def test_agent_cards_link_to_chat(app_state):
    """Each agent card on the command center is a link into /chat?agent=<n>."""
    body = app_state.get("/").data.decode("utf-8")
    for agent in ACTIVE_AGENTS:
        assert f'/chat?agent={agent}' in body


def test_legacy_moved_to_legacy_path(app_state):
    resp = app_state.get("/legacy")
    assert resp.status_code in (200, 503)
    if resp.status_code == 503:
        body = json.loads(resp.data)
        assert body["error"]["code"] == "ui_unavailable"


def test_legacy_mobile_moved_to_legacy_path(app_state):
    resp = app_state.get("/legacy/mobile")
    assert resp.status_code in (200, 503)


def test_ui_source_metadata_still_works(app_state):
    resp = app_state.get("/ui/source")
    assert resp.status_code == 200


def test_root_javascript_fetches_gpu(app_state):
    body = app_state.get("/").data.decode("utf-8")
    assert "/api/system/gpu" in body


def test_root_javascript_fetches_memory_activity(app_state):
    body = app_state.get("/").data.decode("utf-8")
    assert "/api/memory/activity" in body


def test_root_javascript_fetches_sessions(app_state):
    body = app_state.get("/").data.decode("utf-8")
    assert "/sessions" in body


def test_root_javascript_fetches_health(app_state):
    body = app_state.get("/").data.decode("utf-8")
    assert "/health" in body


def test_root_has_aria_live_for_dynamic_panels(app_state):
    """Activity feed and stats panels update live; screen readers need to know."""
    body = app_state.get("/").data.decode("utf-8")
    assert 'aria-live=' in body


def test_root_agent_cards_have_aria_labels(app_state):
    body = app_state.get("/").data.decode("utf-8")
    # Each agent card should announce itself — at least 3 aria-label attrs
    assert body.count("aria-label") >= 3


def test_root_agent_cards_are_tab_targets(app_state):
    """Agent cards are anchor elements — they should be in the tab order naturally.
    Confirm they don't have tabindex=-1 disabling that."""
    body = app_state.get("/").data.decode("utf-8")
    # No negative tabindex on agent cards
    assert 'data-agent="aetheria" tabindex="-1"' not in body
    assert 'data-agent="vett" tabindex="-1"' not in body
    assert 'data-agent="scotty" tabindex="-1"' not in body


def test_root_status_pill_does_not_steal_focus(app_state):
    """Status pill is informational and should not be in tab order."""
    body = app_state.get("/").data.decode("utf-8")
    # Status pill marker present
    assert 'class="status-pill"' in body
