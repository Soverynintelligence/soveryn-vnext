"""Mission Control public-agent glance (SSH → Spark loopback + live CRM)."""

from __future__ import annotations

from unittest.mock import patch

from soveryn.app.services import public_agents as pa
from soveryn.platform.pondwright import crm as pw_crm


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
    return {"agents": {"8200": row, "8400": row, "8500": row}, "waitlist": {"ok": False}}


def _crm_leads():
    return [
        {
            "id": "a",
            "name": "Pat Real",
            "phone": "9105550101",
            "email": "",
            "source": "Referral",
            "status": "new",
            "interest": "cleanout",
            "created_at": "2026-10-02T10:00:00Z",
            "is_test": 0,
        },
        {
            "id": "b",
            "name": "Kim Quoted",
            "phone": "9105550102",
            "status": "quoted",
            "interest": "repair",
            "created_at": "2026-09-30T12:00:00Z",
            "is_test": False,
        },
        {
            "id": "c",
            "name": "Smoke Probe",
            "phone": "0000000000",
            "status": "new",
            "interest": "ignore me",
            "created_at": "2026-10-02T11:00:00Z",
            "is_test": 1,
        },
        {
            "id": "d",
            "name": "Admin Test",
            "status": "new",
            "created_at": "2026-10-02T09:00:00Z",
            "is_test": True,
        },
        {
            "id": "e",
            "name": "New Yesterday",
            "status": "new",
            "created_at": "2026-10-01T18:00:00Z",
        },
    ]


def test_get_public_agents_aggregates_ssh_bundle():
    with patch.object(pa, "_ssh_json_bundle", return_value=_bundle()):
        with patch.object(pa, "_crm_pipeline", return_value={"ok": False}):
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
    assert payload["crm"]["ok"] is False


def test_unreachable_spark_marks_agents_down():
    with patch.object(pa, "_ssh_json_bundle", return_value=None):
        with patch.object(pa, "_crm_pipeline", return_value={"ok": False}):
            with patch.object(pa, "_cache", {"at": 0.0, "payload": None}):
                payload = pa.get_public_agents(force=True)

    assert all(not a["reachable"] for a in payload["agents"])
    assert payload["talking"] == []
    assert payload["path"] is None
    assert payload["crm"]["ok"] is False


def test_crm_pipeline_counts_exclude_is_test():
    glance = pw_crm.summarize_leads(_crm_leads(), today="2026-10-02")
    assert glance["ok"] is True
    assert glance["leads_total"] == 3  # a, b, e — not the two is_test rows
    assert glance["leads_today"] == 1  # only Pat Real
    assert glance["leads_new"] == 2  # Pat Real + New Yesterday
    names = [L["name"] for L in glance["recent"]]
    assert "Smoke Probe" not in names
    assert "Admin Test" not in names
    assert "Pat Real" in names


def test_crm_pipeline_ack_excludes_older_new_leads():
    glance = pw_crm.summarize_leads(
        _crm_leads(), ack="2026-10-01T20:00:00Z", today="2026-10-02"
    )
    assert glance["leads_new"] == 1  # only Pat Real is new and after the ack
    assert glance["ack"] == "2026-10-01T20:00:00Z"


def test_get_public_agents_uses_live_crm_counts():
    crm = pw_crm.summarize_leads(_crm_leads(), today="2026-10-02")
    with patch.object(pa, "_ssh_json_bundle", return_value=_bundle()):
        with patch.object(pa, "_crm_pipeline", return_value=crm):
            with patch.object(pa, "_cache", {"at": 0.0, "payload": None}):
                payload = pa.get_public_agents(force=True)

    assert payload["crm"]["ok"] is True
    assert payload["crm"]["leads_total"] == 3
    assert payload["crm"]["leads_new"] == 2
    assert payload["crm"]["leads_today"] == 1
    pond = next(a for a in payload["agents"] if a["id"] == "pondwright")
    assert pond["leads_captured"] == 3
    assert payload["intake"]["crm_new"] == 2
    assert payload["intake"]["crm_today"] == 1
    assert any(r["who"] == "Pat Real" for r in payload["intake"]["recent"])
    assert not any("Smoke" in (r.get("who") or "") for r in payload["intake"]["recent"])


def test_crm_unavailable_fail_soft_keeps_agents():
    down = {
        "ok": False,
        "error": "crm_unreachable",
        "label": "PondWright CRM",
        "open": "https://crm.pondwright.com/",
    }
    with patch.object(pa, "_ssh_json_bundle", return_value=_bundle()):
        with patch.object(pa, "_crm_pipeline", return_value=down):
            with patch.object(pa, "_cache", {"at": 0.0, "payload": None}):
                payload = pa.get_public_agents(force=True)

    assert payload["crm"]["ok"] is False
    assert payload["crm"]["error"] == "crm_unreachable"
    assert len(payload["agents"]) == 3
    assert all(a["reachable"] for a in payload["agents"])
    pond = next(a for a in payload["agents"] if a["id"] == "pondwright")
    assert pond["leads_captured"] == 1  # chat audit, CRM did not overlay
    assert payload["intake"]["crm_new"] == 0
    assert payload["intake"]["ok"] is False


def test_pipeline_glance_fail_soft_on_http_error(monkeypatch):
    monkeypatch.setattr(
        pw_crm,
        "_request",
        lambda *a, **k: {"ok": False, "error": "crm_unreachable", "detail": "refused"},
    )
    out = pw_crm.pipeline_glance()
    assert out["ok"] is False
    assert out["error"] == "crm_unreachable"
    assert out["label"] == "PondWright CRM"
    assert "leads_total" not in out


def test_pipeline_glance_uses_live_leads_endpoint(monkeypatch):
    seen: list[tuple[str, str]] = []

    def fake_request(method, path, *, body=None, auth=True):
        seen.append((method, path))
        return {"leads": _crm_leads()}

    monkeypatch.setattr(pw_crm, "_request", fake_request)
    monkeypatch.setattr(pw_crm, "datetime", pw_crm.datetime)
    out = pw_crm.summarize_leads(_crm_leads(), today="2026-10-02")
    glance = pw_crm.pipeline_glance()
    assert seen == [("GET", "/api/leads")]
    assert glance["ok"] is True
    assert glance["leads_total"] == out["leads_total"] == 3
    assert glance["leads_today"] >= 0  # clock is live; exclusion still holds
    names = [L["name"] for L in glance["recent"]]
    assert "Smoke Probe" not in names


def test_crm_pipeline_wrapper_swallows_exceptions():
    with patch(
        "soveryn.platform.pondwright.crm.pipeline_glance",
        side_effect=RuntimeError("boom"),
    ):
        out = pa._crm_pipeline()
    assert out["ok"] is False
    assert out["error"] == "RuntimeError"
    assert out["label"] == "PondWright CRM"
