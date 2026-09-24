"""CWG Google Calendar tools — list ungated, create Gate-only."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from soveryn.citizens.connectors import requires_approval
from soveryn.platform.gcal.client import (
    _parse_ics_events,
    complete_event,
    create_event,
    list_events,
)
from soveryn.platform.gcal.config import GcalConfig
from soveryn.platform.gcal.tools import (
    build_eve_calendar_create_tool,
    build_eve_calendar_list_tool,
)
from soveryn.platform.tools.registry import ToolArgError


def _cfg(tmp_path, *, client_id: str = "id", authorized: bool = True) -> GcalConfig:
    token = tmp_path / "tokens.json"
    if authorized:
        token.write_text('{"access_token":"x","refresh_token":"y","expires_at":9999999999}\n')
    return GcalConfig(
        client_id=client_id,
        client_secret="test-gcal-client",  # ggignore
        redirect_uri="http://127.0.0.1:8767/oauth/gcal/callback",
        token_path=token,
        calendar_id="primary",
        timezone="America/New_York",
        ical_url="",
    )


def test_calendar_create_is_always_gated():
    assert requires_approval("eve_calendar_create") is True
    assert requires_approval("eve_calendar_create", source="automation") is True
    assert requires_approval("eve_calendar_list") is False
    assert requires_approval("eve_calendar_status") is False


def test_list_unconfigured_is_honest(tmp_path):
    cfg = _cfg(tmp_path, client_id="", authorized=False)
    out = list_events(cfg=cfg, token="x")
    assert out["ok"] is False
    assert out["status"] == "needs_oauth_client"


def test_list_events_parses_items(tmp_path):
    cfg = _cfg(tmp_path)
    now = datetime(2026, 9, 8, 9, 0, tzinfo=ZoneInfo("America/New_York"))

    def http(url, *, method="GET", token="", body=None):
        assert method == "GET"
        assert "calendars/primary/events" in url
        return {
            "items": [
                {
                    "id": "abc",
                    "summary": "Pond clean",
                    "start": {"dateTime": "2026-09-08T10:00:00-04:00"},
                    "end": {"dateTime": "2026-09-08T12:00:00-04:00"},
                    "location": "Pinehurst",
                    "htmlLink": "https://calendar.google.com/event?eid=abc",
                }
            ]
        }

    out = list_events(cfg=cfg, token="tok", http=http, now=now, days=7)
    assert out["ok"] is True
    assert out["count"] == 1
    assert out["events"][0]["summary"] == "Pond clean"
    assert out["events"][0]["location"] == "Pinehurst"
    assert out["events"][0]["cwg_status"] == "open"


def test_complete_event_patches_done(tmp_path):
    cfg = _cfg(tmp_path)
    seen: list = []

    def http(url, *, method="GET", token="", body=None):
        seen.append((method, url, body))
        if method == "GET":
            return {"id": "abc", "summary": "Molly fountain"}
        return {
            "id": "abc",
            "summary": "[DONE] Molly fountain",
            "htmlLink": "https://calendar.google.com/event?eid=abc",
        }

    out = complete_event(event_id="abc", cfg=cfg, token="tok", http=http)
    assert out["ok"] is True
    assert out["cwg_status"] == "done"
    assert seen[0][0] == "GET"
    assert seen[1][0] == "PATCH"
    assert seen[1][2]["extendedProperties"]["private"]["cwgStatus"] == "done"
    assert seen[1][2]["summary"].startswith("[DONE]")


def test_create_event_posts(tmp_path):
    cfg = _cfg(tmp_path)
    seen: list = []

    def http(url, *, method="GET", token="", body=None):
        seen.append((method, url, body))
        return {
            "id": "evt1",
            "summary": body["summary"],
            "htmlLink": "https://calendar.google.com/event?eid=evt1",
        }

    out = create_event(
        summary="Site visit",
        start="2026-09-08T10:00",
        cfg=cfg,
        token="tok",
        http=http,
    )
    assert out["ok"] is True
    assert out["status"] == "created"
    assert seen[0][0] == "POST"
    assert seen[0][2]["summary"] == "Site visit"
    assert seen[0][2]["start"]["timeZone"] == "America/New_York"


def test_create_tool_requires_summary():
    spec = build_eve_calendar_create_tool(create_fn=lambda **_k: {"ok": True})
    with pytest.raises(ToolArgError):
        spec.handler({"start": "2026-09-08T10:00"})


def test_parse_ics_events_reads_vevent():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:abc
DTSTART:20260908T140000Z
DTEND:20260908T160000Z
SUMMARY:Pond clean
LOCATION:Pinehurst
END:VEVENT
END:VCALENDAR
"""
    ev = _parse_ics_events(ics, tz_name="America/New_York")
    assert len(ev) == 1
    assert ev[0]["summary"] == "Pond clean"
    assert ev[0]["location"] == "Pinehurst"


def test_list_tool_rejects_bad_days():
    spec = build_eve_calendar_list_tool()
    with pytest.raises(ToolArgError):
        spec.handler({"days": 0})
