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
            assert body and body.get("source") == "Phone/text unknown"
            assert body.get("job_type") == "Repair"
            return {"ok": True, "id": "new1", "merged": False, "lead": {"id": "new1", "name": "Pat"}}
        if method == "GET" and path == "/api/leads/new1":
            return {"lead": {"id": "new1", "name": "Pat", "message": ""}}
        if method == "PATCH" and path == "/api/leads/new1":
            return {"lead": {"id": "new1", "name": "Pat", "message": "called back"}}
        return {"ok": False, "error": f"unexpected {method} {path}"}

    monkeypatch.setattr(pw_crm, "_request", fake_request)
    out = pw_crm.save_lead({"name": "Pat", "phone": "910-555-0101", "note": "called back about a leak"})
    assert out["ok"] is True
    assert out["lead_id"] == "new1"
    assert out["created"] is True


def _no_http(monkeypatch):
    calls: list = []

    def fake_request(method, path, *, body=None, auth=True):
        calls.append((method, path, body))
        return {"ok": True}

    monkeypatch.setattr(pw_crm, "_request", fake_request)
    return calls


def test_save_lead_without_phone_or_email_does_not_call_crm(monkeypatch):
    calls = _no_http(monkeypatch)
    out = pw_crm.save_lead({"name": "Ervin", "job_type": "Cleanout"})
    assert out["ok"] is False and out["needs"] == "phone_or_email"
    assert "Ask Jon" in out["message"] and "Ervin" in out["message"]
    assert calls == []


def test_save_lead_unclear_job_does_not_call_crm(monkeypatch):
    calls = _no_http(monkeypatch)
    out = pw_crm.save_lead({"name": "Sam", "phone": "9105550199", "note": "wants a call"})
    assert out["ok"] is False and out["needs"] == "job_type"
    assert "Ask Jon what the job is" in out["message"]
    assert calls == []


def test_job_type_inference_keywords():
    cases = {
        "spring cleanout": "Cleanout",
        "pond is green, algae everywhere": "Green water",
        "pump died, maybe a leak": "Repair",
        "wants a waterfall and stream": "Waterfall/stream",
        "natural swim pond": "Swim pond",
        "build a pond out back": "New pond build",
        "remodel the old pond": "Remodel/rebuild",
        "maintenance plan, twice a year": "Maintenance plan",
        "wants a call": "",
    }
    for text, want in cases.items():
        assert pw_crm.infer_job_type(text) == want, text
    assert pw_crm.pick_job_type("green WATER") == "Green water"
    assert pw_crm.pick_source("") == "Phone/text unknown"
    assert pw_crm.pick_source("website") == "Website/Google search"
    assert pw_crm.pick_source("Nextdoor") == "Nextdoor"


def test_save_lead_explicit_job_type_and_source_sent(monkeypatch):
    seen = {}

    def fake_request(method, path, *, body=None, auth=True):
        seen.update(body or {})
        return {"ok": True, "id": "n2", "merged": False, "lead": {"id": "n2", "name": "Kim"}}

    monkeypatch.setattr(pw_crm, "_request", fake_request)
    out = pw_crm.save_lead({"name": "Kim", "email": "kim@example.com", "job_type": "Swim pond", "source": "Referral"})
    assert out["created"] is True
    assert seen["job_type"] == "Swim pond" and seen["source"] == "Referral"
    assert seen["email"] == "kim@example.com"


def test_save_lead_merged_message(monkeypatch):
    def fake_request(method, path, *, body=None, auth=True):
        assert method == "POST"
        return {"ok": True, "id": "abc123", "merged": True, "lead": {"id": "abc123", "name": "Molly Thomas", "status": "won"}}

    monkeypatch.setattr(pw_crm, "_request", fake_request)
    out = pw_crm.save_lead({"name": "Molly", "phone": "(910) 963-4077", "job_type": "Repair", "status": "new"})
    assert out["ok"] is True and out["merged"] is True and out["created"] is False
    assert out["message"] == "Already in CRM as Molly Thomas (id abc123); added your note to the existing lead."
    assert "status_note" in out  # status not pushed onto the existing lead


def test_save_lead_422_is_reported_plainly(monkeypatch):
    """Real _request path: urlopen raises HTTPError 422 with FastAPI's detail body."""
    import io
    import urllib.error

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 422, "Unprocessable", {}, io.BytesIO(b'{"detail": "Need phone or email for Ervin"}')
        )

    monkeypatch.setattr(pw_crm, "crm_basic", lambda: ("eve", "x"))
    monkeypatch.setattr(pw_crm.urllib.request, "urlopen", fake_urlopen)
    out = pw_crm.save_lead({"name": "Ervin", "phone": "910-555-0123", "job_type": "Cleanout"})
    assert out["ok"] is False and out["rejected"] is True and out["http"] == 422
    assert out["message"] == "CRM rejected: Need phone or email for Ervin"
    assert "Do not retry with blank" in out["instruction"]


def test_save_lead_tool_schema_has_enums():
    reg = ToolRegistry()
    register_pondwright_tools(reg, owner_agent="eve")
    from soveryn.platform.pondwright.tools import build_save_lead_tool

    props = build_save_lead_tool(owner_agent="eve").schema["properties"]
    assert props["job_type"]["enum"] == list(pw_crm.LEAD_JOB_TYPES)
    assert props["source"]["enum"] == list(pw_crm.LEAD_SOURCES)
    assert props["source"]["default"] == "Phone/text unknown"


def test_save_quote_new_lead_uses_mode_for_job_type(monkeypatch):
    posted = {}

    def fake_request(method, path, *, body=None, auth=True):
        if method == "POST" and path == "/api/leads":
            posted.update(body or {})
            return {"ok": True, "id": "q1", "merged": False, "lead": {"id": "q1", "name": "Lee"}}
        if method == "GET" and path == "/api/leads/q1":
            return {"lead": {"id": "q1", "name": "Lee", "job_id": "j1"}}
        if method == "POST" and path == "/api/jobs/j1/quote":
            return {"ok": True}
        return {"ok": False, "error": f"unexpected {method} {path}"}

    monkeypatch.setattr(pw_crm, "_request", fake_request)
    out = pw_crm.save_quote({"name": "Lee", "phone": "9105550144", "mode": "repair", "total": 300})
    assert out["ok"] is True
    assert posted["job_type"] == "Repair"


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


def test_summarize_leads_excludes_is_test_and_counts_pipeline():
    leads = [
        {"id": "1", "name": "Real", "status": "new", "created_at": "2026-10-02T08:00:00Z", "is_test": 0},
        {"id": "2", "name": "Quoted", "status": "quoted", "created_at": "2026-10-02T09:00:00Z"},
        {"id": "3", "name": "Probe", "status": "new", "created_at": "2026-10-02T10:00:00Z", "is_test": True},
        {"id": "4", "name": "Old new", "status": "new", "created_at": "2026-09-01T00:00:00Z", "is_test": "0"},
    ]
    out = pw_crm.summarize_leads(leads, today="2026-10-02")
    assert out["ok"] is True
    assert out["leads_total"] == 3
    assert out["leads_today"] == 2
    assert out["leads_new"] == 2
    assert [L["name"] for L in out["recent"]] == ["Quoted", "Real", "Old new"]


def test_pipeline_glance_http_failure_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        pw_crm, "_request",
        lambda *a, **k: {"ok": False, "error": "crm_unreachable"},
    )
    out = pw_crm.pipeline_glance(ack="2026-10-01T00:00:00Z")
    assert out["ok"] is False
    assert out["error"] == "crm_unreachable"
    assert out["open"] == "https://crm.pondwright.com/"
