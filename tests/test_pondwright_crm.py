"""PondWright CRM tools talk to the existing CRM over HTTP — no second store."""
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
        if method == "POST" and path == "/quote":
            return {"ok": True, "lead_id": "abc", "status": "quoted", "created_lead": False}
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
    assert any(c[0] == "POST" and c[1] == "/quote" for c in calls)


def test_save_lead_creates_then_notes(monkeypatch):
    def fake_request(method, path, *, body=None, auth=True):
        if method == "POST" and path == "/lead":
            assert auth is False
            return {"ok": True, "id": "new1"}
        if method == "POST" and path.endswith("/note"):
            return {"ok": True}
        if method == "GET" and path == "/lead/new1":
            return {"ok": True, "id": "new1", "name": "Pat"}
        return {"ok": False, "error": f"unexpected {method} {path}"}

    monkeypatch.setattr(pw_crm, "_request", fake_request)
    out = pw_crm.save_lead({"name": "Pat", "note": "called back"})
    assert out["ok"] is True
    assert out["lead_id"] == "new1"
    assert out["created"] is True
