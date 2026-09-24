"""PondWright CRM tools talk to pondwright-cwg-ops over HTTP — no second store."""
from __future__ import annotations

from soveryn.platform.pondwright import crm as pw_crm
from soveryn.platform.pondwright.tools import register_pondwright_tools
from soveryn.platform.tools.registry import ToolRegistry


def test_list_and_save_quote_use_crm_http(monkeypatch):
    calls: list[tuple[str, str, dict | None]] = []

    def fake_request(method, path, *, body=None, auth=True):
        calls.append((method, path, body))
        if method == "GET" and path == "/api/leads":
            return {
                "leads": [
                    {
                        "id": "abc",
                        "name": "Molly Thomas",
                        "phone": "9109634077",
                        "email": "mollythomas39@gmail.com",
                        "status": "quoted",
                    }
                ]
            }
        if method == "GET" and path == "/api/leads/abc":
            return {"lead": {"id": "abc", "name": "Molly Thomas", "job_id": "job1"}}
        if method == "POST" and path == "/api/jobs/job1/quote":
            return {"ok": True, "job": {"id": "job1", "quote_total": 705}}
        return {"ok": True}

    monkeypatch.setattr(pw_crm, "_request", fake_request)
    reg = ToolRegistry()
    register_pondwright_tools(reg, owner_agent="eve")

    listed = reg.invoke("eve", "pondwright_leads", {"query": "molly"})
    assert listed["ok"] is True
    assert listed["count"] == 1
    assert listed["leads"][0]["name"] == "Molly Thomas"

    saved = reg.invoke(
        "eve",
        "pondwright_save_quote",
        {
            "lead_id": "abc",
            "total": 705,
            "summary": "Bubbling rock clean-up",
            "lines": [{"desc": "Labor", "amount": 450}],
        },
    )
    assert saved["ok"] is True
    assert saved["lead_id"] == "abc"
    assert any(c[0] == "POST" and c[1] == "/api/jobs/job1/quote" for c in calls)


def test_save_lead_creates_then_notes(monkeypatch):
    def fake_request(method, path, *, body=None, auth=True):
        if method == "POST" and path == "/api/leads":
            assert auth is True
            assert body and body.get("source") == "eve"
            return {"ok": True, "lead": {"id": "new1", "name": "Pat"}}
        if method == "GET" and path == "/api/leads/new1":
            return {"lead": {"id": "new1", "name": "Pat", "message": ""}}
        if method == "PATCH" and path == "/api/leads/new1":
            return {"lead": {"id": "new1", "name": "Pat", "message": "called back"}}
        return {"ok": False, "error": f"unexpected {method} {path}"}

    monkeypatch.setattr(pw_crm, "_request", fake_request)
    out = pw_crm.save_lead({"name": "Pat", "note": "called back"})
    assert out["ok"] is True
    assert out["lead_id"] == "new1"
    assert out["created"] is True


def test_list_leads_does_not_treat_401_as_empty(monkeypatch):
    def fake_request(method, path, *, body=None, auth=True):
        return {
            "detail": "auth required",
            "ok": False,
            "http": 401,
            "error": "auth required",
        }

    monkeypatch.setattr(pw_crm, "_request", fake_request)
    listed = pw_crm.list_leads()
    assert listed.get("ok") is False
    assert listed.get("http") == 401
    assert listed.get("error")


def test_401_without_error_key_is_still_failure():
    assert pw_crm._failed({"detail": "auth required", "ok": False, "http": 401}) is True
    assert pw_crm._failed({"leads": []}) is False
