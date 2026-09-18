"""PondWright lead watch pings Messages PWA; admin stays quiet; first tick seeds."""
from __future__ import annotations

from soveryn.platform.pondwright.lead_watch import load_seen, should_ping_source, tick
from soveryn.platform.webpush.notify import notify_pondwright_lead


def test_admin_source_is_quiet():
    assert should_ping_source("admin") is False
    assert should_ping_source("ADMIN") is False
    assert should_ping_source("search-organic/quick-ask") is True
    assert should_ping_source("eve") is True
    assert should_ping_source("website") is True
    assert should_ping_source("smoke") is False


def test_first_tick_seeds_without_pinging(tmp_path):
    state = tmp_path / "seen.json"
    pings: list[dict] = []

    def list_leads(limit=100):
        return {
            "ok": True,
            "leads": [
                {"id": "old1", "name": "Molly", "source": "eve"},
                {"id": "old2", "name": "Cliff", "source": "admin"},
            ],
        }

    out = tick(list_leads=list_leads, notify=pings.append, state_path=state)
    assert out["ok"] is True
    assert out["seeded"] == 2
    assert out["pinged"] == 0
    assert pings == []
    assert load_seen(state) == {"old1", "old2"}


def test_new_organic_lead_pings_admin_does_not(tmp_path):
    state = tmp_path / "seen.json"
    state.write_text('{"seen": ["old1"]}\n')
    pings: list[dict] = []
    leads = [
        {"id": "old1", "name": "Molly", "source": "eve"},
        {
            "id": "tracy",
            "name": "Tracy West",
            "source": "search-organic/quick-ask",
            "wants": "cement pond",
            "city": "Laurinburg",
        },
        {"id": "cliff", "name": "Cliff Patterson", "source": "admin"},
    ]

    def list_leads(limit=100):
        return {"ok": True, "leads": leads}

    out = tick(list_leads=list_leads, notify=pings.append, state_path=state)
    assert out["pinged"] == 1
    assert pings[0]["id"] == "tracy"
    assert "cliff" in load_seen(state)
    assert "tracy" in load_seen(state)


def test_notify_payload_shape(monkeypatch):
    sent = {}

    def fake_notify_needs_you(**kwargs):
        sent.update(kwargs)

    monkeypatch.setattr(
        "soveryn.platform.webpush.notify.notify_needs_you", fake_notify_needs_you
    )
    notify_pondwright_lead(
        {
            "id": "abc",
            "name": "Tracy West",
            "source": "search-organic/quick-ask",
            "wants": "cement pond being poured needs plumbing and filters",
            "city": "Laurinburg",
        }
    )
    assert sent["title"].startswith("PondWright · Tracy")
    assert "search-organic" in sent["body"]
    assert "Laurinburg" in sent["body"]
    assert sent["url"] == "https://crm.pondwright.com/"
    assert sent["tag"] == "pondwright-lead-abc"


def test_list_failure_does_not_seed(tmp_path):
    state = tmp_path / "seen.json"

    def list_leads(limit=100):
        return {"ok": False, "error": "auth required", "http": 401}

    out = tick(list_leads=list_leads, notify=lambda L: None, state_path=state)
    assert out["ok"] is False
    assert not state.exists()
