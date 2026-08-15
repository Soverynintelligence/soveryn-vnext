"""Mission Control public-agent glance (SSH → Spark loopback)."""

from __future__ import annotations

from unittest.mock import patch

from soveryn.app.services import public_agents as pa


def _bundle():
    row = {
        "summary": {
            "enabled": True,
            "conversations_today": 2,
            "conversations_total": 10,
            "turns_today": 5,
            "leads_captured": 1,
            "last_activity": "2026-08-15T12:00:00",
            "recent": [{"ts": "2026-08-15T12:00:00", "preview": "hello", "captured": False}],
        },
        "health": {"ok": True, "model_ok": True, "model": "lightning-30b", "enabled": True},
        "error": None,
    }
    return {"8200": row, "8400": row, "8500": row}


def test_get_public_agents_aggregates_ssh_bundle():
    with patch.object(pa, "_ssh_json_bundle", return_value=_bundle()):
        with patch.object(pa, "_cache", {"at": 0.0, "payload": None}):
            payload = pa.get_public_agents(force=True)

    assert len(payload["agents"]) == 3
    ids = {a["id"] for a in payload["agents"]}
    assert ids == {"pondwright", "seneca", "atticus"}
    for a in payload["agents"]:
        assert a["reachable"] is True
        assert a["conversations_today"] == 2
        assert a["recent"][0]["preview"] == "hello"
    assert set(payload["talking"]) == ids
    assert payload["path"] == "fabric"


def test_unreachable_spark_marks_agents_down():
    with patch.object(pa, "_ssh_json_bundle", return_value=None):
        with patch.object(pa, "_cache", {"at": 0.0, "payload": None}):
            payload = pa.get_public_agents(force=True)

    assert all(not a["reachable"] for a in payload["agents"])
    assert payload["talking"] == []
    assert payload["path"] is None
