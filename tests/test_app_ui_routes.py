"""Tests for soveryn/app/routes/ui.py — Messages front door; desk at /command-center."""

import json
import re
import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS, MESSAGES_CONTACTS
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
    """cc-redesign: the greeting moved to House; Desk leads with the work."""
    assert 'data-testid="greeting"' in app_state.get("/house").data.decode("utf-8")
    body = app_state.get("/command-center").data.decode("utf-8")
    for tid in ("agent-row", "kernel-pane", "needs-you", "today-results", "status-strip"):
        assert f'data-testid="{tid}"' in body


def test_desk_has_no_dead_gpu_or_spark_polling(app_state):
    body = app_state.get("/command-center").data.decode("utf-8")
    assert "/api/system/gpu" not in body and "/api/system/spark" not in body


def test_desk_has_agent_row_with_active_agents(app_state):
    body = app_state.get("/command-center").data.decode("utf-8").lower()
    for agent in MESSAGES_CONTACTS:
        assert f'data-agent="{agent}"' in body
    for parked in ("vett", "scotty"):
        assert f'class="agent-card" data-agent="{parked}"' not in body


def test_desk_has_lattice_telemetry(app_state):
    """Lattice write rate stays on Desk with the other memory surfaces."""
    body = app_state.get("/house").data.decode("utf-8")
    assert 'data-testid="lattice-telemetry"' in body


def test_fleet_redirects_to_estate(app_state):
    """Fleet merged into Estate; old bookmarks 302 and keep their query."""
    r = app_state.get("/fleet", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers.get("Location", "").endswith("/estate")
    r = app_state.get("/fleet?x=1", follow_redirects=False)
    assert r.headers.get("Location", "").endswith("/estate?x=1")


def test_estate_page_has_rig_sessions_and_counts(app_state):
    """Estate owns Rig + session traffic + house counts (from Fleet) and House ops."""
    resp = app_state.get("/estate")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'data-testid="estate-page"' in body
    for tid in ("ares-panel", "daemons-panel", "gate-panel", "public-agents", "automations-panel"):
        assert f'data-testid="{tid}"' in body
    assert 'data-testid="rig"' in body
    assert 'data-testid="activity-feed"' in body
    assert 'data-testid="system-panel"' in body


def test_desk_no_hardcoded_retired_agents(app_state):
    body = app_state.get("/command-center").data.decode("utf-8").lower()
    for retired in ("scout", "vision", "tinker", "ares_llm"):
        assert retired not in body, f"hardcoded retired {retired!r} in command center"


def test_estate_no_hardcoded_gpu_labels_in_rig_cards(app_state):
    """Guards against hardcoded GPU model names in Estate Rig cards."""
    body = app_state.get("/estate").data.decode("utf-8").lower()
    start = body.find('data-rig-gpus')
    assert start >= 0, "rig GPU cards container missing from estate page"
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
    for agent in MESSAGES_CONTACTS:
        assert f'/messages/{agent}' in body
    assert "/messages/vett" not in body
    assert "/messages/scotty" not in body


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


def test_estate_javascript_fetches_rig(app_state):
    body = app_state.get("/estate").data.decode("utf-8")
    assert "/api/system/rig" in body


def test_desk_javascript_fetches_memory_activity(app_state):
    body = app_state.get("/house").data.decode("utf-8")
    assert "/api/memory/activity" in body


def test_estate_javascript_fetches_sessions(app_state):
    body = app_state.get("/estate").data.decode("utf-8")
    assert "/sessions" in body


def test_desk_javascript_fetches_health(app_state):
    body = app_state.get("/house").data.decode("utf-8")
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
    assert 'class="agent-card" data-agent="vett"' not in body
    assert 'class="agent-card" data-agent="scotty"' not in body


def test_desk_status_pill_does_not_steal_focus(app_state):
    """Status pill is informational and should not be in tab order."""
    body = app_state.get("/command-center").data.decode("utf-8")
    # cc-redesign: status strip of plain <span> pills (never tab targets)
    assert 'data-testid="status-strip"' in body
    assert 'tabindex' not in body.split('data-testid="status-strip"', 1)[1].split("</div>", 1)[0]


def test_messages_inlines_citizen_icons_js_with_regex_escapes(app_state):
    """citizen-icons.js contains `\\w`; inlining must not re.sub it as a backref."""
    resp = app_state.get("/messages", follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "internal_error" not in body
    assert "soverynCitizenIcon" in body
    assert "openPicker" in body


SD_PAGES = ("/command-center", "/estate", "/citizens", "/documents", "/house")


def test_shared_nav_on_every_desk_style_page(app_state):
    """One nav, five doors, same order, on every Desk-style page; marker never leaks."""
    for page in SD_PAGES:
        body = app_state.get(page).data.decode("utf-8")
        assert body.count('data-testid="sd-nav"') == 1, page
        assert "<!--sd-nav:" not in body, page
        nav = body[body.find('data-testid="sd-nav"'):]
        nav = nav[: nav.find("</nav>")]
        order = [nav.find(f'href="{h}"') for h in
                 ("/command-center", "/messages", "/citizens", "/estate", "/documents", "/house")]
        assert all(i > 0 for i in order) and order == sorted(order), page
        assert nav.count('aria-current="page"') == 1, page


def test_messages_pages_have_sidebar_nav_and_keep_pwa(app_state):
    """Messages redesign: sidebar + status dots + shared nav, PWA/push/streaming intact."""
    for page in ("/messages", "/messages/eve"):
        r = app_state.get(page, follow_redirects=True)
        assert r.status_code == 200
        body = r.data.decode("utf-8")
        assert body.count('data-testid="messages-sidebar"') == 1, page
        assert body.count('data-testid="sd-nav"') == 1, page
        assert "<!--mx-sidebar-->" not in body and "<!--sd-nav:" not in body, page
        for keep in ('rel="manifest"', "apple-mobile-web-app-capable", "/messages-push-client.js",
                     "data-push-banner", "/api/messages/presence", "/api/messages/sidebar"):
            assert keep in body, (page, keep)
    thread = app_state.get("/messages/eve", follow_redirects=True).data.decode("utf-8")
    assert "/chat_stream" in thread and 'data-mx-page="thread"' in thread
    home = app_state.get("/messages", follow_redirects=True).data.decode("utf-8")
    assert 'data-mx-page="home"' in home and 'data-testid="messages-list"' in home and "data-push-allow" in home


def test_messages_presence_and_sidebar_api_shape(app_state):
    r = app_state.get("/api/messages/presence")
    assert r.status_code == 200
    ids = [c["id"] for c in r.get_json()["citizens"]]
    assert ids[:3] == ["aetheria", "forge", "eve"]
    for c in r.get_json()["citizens"]:
        assert c["state"] in ("live", "busy", "down", "inbox")
    r = app_state.get('/api/messages/sidebar?since={"eve":"2026-01-01T00:00:00Z"}')
    assert r.status_code == 200
    rows = {c["id"]: c for c in r.get_json()["contacts"]}
    assert set(rows) >= {"aetheria", "forge", "eve"}
    assert all(isinstance(c["unread"], int) for c in rows.values())
    assert app_state.get("/api/messages/sidebar?since=not-json").status_code == 200


def test_staff_page_desk_style_keeps_board_hooks(app_state):
    """Staff restyle keeps every hook the board JS + citizens tests use; kill UI is gone."""
    body = app_state.get("/citizens").data.decode("utf-8")
    for hook in ("data-roster", "data-commission-form", "data-post-form", "data-posts",
                 "data-commissions", "data-spawned-list", "data-house-health", "data-refresh",
                 'data-testid="spawned-panel"', "/api/citizens/post", "/api/citizens/refresh"):
        assert hook in body, hook
    assert "data-kill-specialist" not in body
    assert "/api/specialists/kill" not in body
    assert "/static/lab-console.css" not in body and "softdesk.css" not in body


def test_library_has_documents_memory_and_links(app_state):
    body = app_state.get("/documents").data.decode("utf-8")
    assert 'data-testid="library-page"' in body
    assert 'data-testid="documents-pane"' in body and 'data-testid="memory-panel"' in body
    for api in ("/api/documents", "/api/memory/browse", "/api/memory/facets", "/api/memory/node/"):
        assert api in body, api
    assert 'href="/cathedral"' in body and 'href="/charters"' in body
    # agent filter is built from the data, not a stale hardcoded roster
    assert 'value="vett"' not in body and 'value="scotty"' not in body
    # markdown links are restricted to http(s), / or #
    assert "function safeHref" in body
