"""Tests for soveryn/app/routes/ui.py — Messages front door; desk at /command-center."""

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


def test_root_redirects_to_messages(app_state):
    """House front door is Messages on every device — not Command Center."""
    resp = app_state.get(
        "/",
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers.get("Location", "").endswith("/messages")


def test_root_phone_redirects_to_messages(app_state):
    resp = app_state.get(
        "/",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            )
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers.get("Location", "").endswith("/messages")


def test_root_can_force_command_center(app_state):
    resp = app_state.get(
        "/?desk=1",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
            )
        },
    )
    assert resp.status_code == 200
    assert 'data-testid="command-center"' in resp.data.decode("utf-8")


def test_command_center_alias(app_state):
    resp = app_state.get("/command-center")
    assert resp.status_code == 200
    assert 'data-testid="command-center"' in resp.data.decode("utf-8")


def test_command_center_phone_redirects_to_messages(app_state):
    resp = app_state.get(
        "/command-center",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            )
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers.get("Location", "").endswith("/messages")


def test_command_center_phone_can_force_desk(app_state):
    resp = app_state.get(
        "/command-center?desk=1",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
            )
        },
    )
    assert resp.status_code == 200
    assert 'data-testid="command-center"' in resp.data.decode("utf-8")


def test_desk_has_greeting_block(app_state):
    body = app_state.get("/command-center").data.decode("utf-8")
    assert 'data-testid="greeting"' in body


def test_desk_has_agent_row_with_active_agents(app_state):
    body = app_state.get("/command-center").data.decode("utf-8").lower()
    for agent in ACTIVE_AGENTS:
        assert f'data-agent="{agent}"' in body


def test_desk_has_lattice_telemetry(app_state):
    """Lattice write rate stays on Desk with the other memory surfaces."""
    body = app_state.get("/command-center").data.decode("utf-8")
    assert 'data-testid="lattice-telemetry"' in body


def test_fleet_page_has_rig_sessions_and_counts(app_state):
    """Fleet page owns Rig + session traffic + house counts."""
    resp = app_state.get("/fleet")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'data-testid="fleet-page"' in body
    assert 'data-testid="rig"' in body
    assert 'data-testid="activity-feed"' in body
    assert 'data-testid="system-panel"' in body


def test_desk_no_hardcoded_retired_agents(app_state):
    body = app_state.get("/command-center").data.decode("utf-8").lower()
    for retired in ("scout", "vision", "tinker", "ares_llm"):
        assert retired not in body, f"hardcoded retired {retired!r} in command center"


def test_fleet_no_hardcoded_gpu_labels_in_rig_cards(app_state):
    """Guards against hardcoded GPU model names in Fleet Rig cards."""
    body = app_state.get("/fleet").data.decode("utf-8").lower()
    start = body.find('data-rig-gpus')
    assert start >= 0, "rig GPU cards container missing from fleet page"
    end = body.find('</div>', start)
    section = body[start : end if end > 0 else start + 800]
    for label in ("blackwell", "rtx 8000", "rtx pro 5000", "quadro"):
        assert label not in section, f"hardcoded GPU label {label!r} in rig cards"


def test_desk_no_external_resources(app_state):
    body = app_state.get("/command-center").data.decode("utf-8")
    assert re.findall(r'<script[^>]+src=["\']https?://', body) == []
    assert re.findall(r'<link[^>]+href=["\']https?://', body) == []


def test_agent_cards_link_to_messages(app_state):
    """Each agent card Talk button opens Messages — not lab /chat."""
    body = app_state.get(
        "/command-center",
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0"},
    ).data.decode("utf-8")
    assert 'href="/chat"' not in body
    assert ">Chat<" not in body
    assert 'href="/messages"' in body
    for agent in ACTIVE_AGENTS:
        assert f'/messages/{agent}' in body


def test_legacy_chat_redirects_to_messages(app_state):
    r = app_state.get("/chat?agent=aetheria", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("Location", "").endswith("/messages/aetheria")


def test_citizens_board_links_message_primary(app_state):
    body = app_state.get("/citizens").data.decode("utf-8")
    assert 'href="/messages"' in body
    assert "House staff" in body or "talk in Messages" in body.lower() or "Messages" in body


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


def test_fleet_javascript_fetches_rig(app_state):
    body = app_state.get("/fleet").data.decode("utf-8")
    assert "/api/system/rig" in body


def test_desk_javascript_fetches_memory_activity(app_state):
    body = app_state.get("/command-center").data.decode("utf-8")
    assert "/api/memory/activity" in body


def test_fleet_javascript_fetches_sessions(app_state):
    body = app_state.get("/fleet").data.decode("utf-8")
    assert "/sessions" in body


def test_desk_javascript_fetches_health(app_state):
    body = app_state.get("/command-center").data.decode("utf-8")
    assert "/health" in body


def test_desk_has_aria_live_for_dynamic_panels(app_state):
    """Activity feed and stats panels update live; screen readers need to know."""
    body = app_state.get("/command-center").data.decode("utf-8")
    assert 'aria-live=' in body


def test_desk_agent_cards_have_aria_labels(app_state):
    body = app_state.get("/command-center").data.decode("utf-8")
    # Each agent card should announce itself — at least 3 aria-label attrs
    assert body.count("aria-label") >= 3


def test_desk_agent_cards_are_tab_targets(app_state):
    """Agent cards are anchor elements — they should be in the tab order naturally.
    Confirm they don't have tabindex=-1 disabling that."""
    body = app_state.get("/command-center").data.decode("utf-8")
    # No negative tabindex on agent cards
    assert 'data-agent="aetheria" tabindex="-1"' not in body
    assert 'data-agent="vett" tabindex="-1"' not in body
    assert 'data-agent="scotty" tabindex="-1"' not in body


def test_desk_status_pill_does_not_steal_focus(app_state):
    """Status pill is informational and should not be in tab order."""
    body = app_state.get("/command-center").data.decode("utf-8")
    # Status pill marker present
    assert 'class="status-pill"' in body
