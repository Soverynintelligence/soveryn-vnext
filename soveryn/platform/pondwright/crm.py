"""PondWright CRM client — the CWG lead / quote / job pipeline.

One store: the PondWright CRM (Spark, tunneled at 127.0.0.1:8100, public
https://crm.pondwright.com). Citizens talk to it over HTTP with the field
token. They do not write leads into the lattice.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_DEFAULT_URL = "http://127.0.0.1:8100"
_CFG = Path.home() / "pondwright-crm" / "config.json"
_TOKEN_FILE = Path.home() / "pondwright-crm" / ".field_token_live"
_TIMEOUT = 12


def crm_base() -> str:
    raw = (os.environ.get("SOVERYN_PONDWRIGHT_CRM_URL") or "").strip()
    return raw.rstrip("/") if raw else _DEFAULT_URL


def crm_token() -> str:
    env = (os.environ.get("SOVERYN_PONDWRIGHT_CRM_TOKEN") or "").strip()
    if env:
        return env
    if _TOKEN_FILE.is_file():
        return _TOKEN_FILE.read_text(encoding="utf-8").strip()
    if _CFG.is_file():
        try:
            data = json.loads(_CFG.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return str(data.get("field_token") or "").strip()
    return ""


def _request(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    auth: bool = True,
) -> dict[str, Any]:
    url = crm_base() + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if auth:
        token = crm_token()
        if not token:
            return {
                "ok": False,
                "error": "crm_token_missing",
                "hint": "Set SOVERYN_PONDWRIGHT_CRM_TOKEN or pondwright-crm/.field_token_live",
            }
        headers["Authorization"] = f"Bearer {token}"
        headers["X-PondWright-Token"] = token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {"ok": True, "data": parsed}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:400]
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict):
                parsed.setdefault("ok", False)
                parsed.setdefault("http", e.code)
                return parsed
        except json.JSONDecodeError:
            pass
        return {"ok": False, "error": f"http_{e.code}", "detail": detail, "http": e.code}
    except urllib.error.URLError as e:
        return {"ok": False, "error": "crm_unreachable", "detail": str(e.reason)}
    except json.JSONDecodeError:
        return {"ok": False, "error": "bad_json"}


def crm_status() -> dict[str, Any]:
    health = _request("GET", "/health", auth=False)
    return {
        "ok": bool(health.get("ok")),
        "base": crm_base(),
        "token_configured": bool(crm_token()),
        "health": health,
    }


def list_leads(*, status: str | None = None, query: str | None = None, limit: int = 40) -> dict[str, Any]:
    out = _request("GET", "/api/leads")
    if not out.get("ok", True) and out.get("error"):
        return out
    leads = list(out.get("leads") or [])
    if status:
        leads = [L for L in leads if (L.get("status") or "") == status]
    q = (query or "").strip().lower()
    if q:
        def _hit(L: dict[str, Any]) -> bool:
            blob = " ".join(
                str(L.get(k) or "")
                for k in ("name", "phone", "email", "interest", "source", "id")
            ).lower()
            return q in blob
        leads = [L for L in leads if _hit(L)]
    leads = leads[: max(1, min(int(limit), 100))]
    return {"ok": True, "count": len(leads), "leads": leads}


def get_lead(lead_id: str) -> dict[str, Any]:
    lid = (lead_id or "").strip()
    if not lid:
        return {"ok": False, "error": "lead_id required"}
    out = _request("GET", f"/lead/{urllib.parse.quote(lid)}")
    if out.get("error") and not out.get("ok", True):
        return out
    if out.get("id") or out.get("lead") or out.get("quotes") is not None:
        out.setdefault("ok", True)
    return out


def save_lead(payload: dict[str, Any]) -> dict[str, Any]:
    lid = str(payload.get("lead_id") or "").strip()
    note = str(payload.get("note") or "").strip()
    status = str(payload.get("status") or "").strip()
    if lid:
        results: dict[str, Any] = {"ok": True, "lead_id": lid}
        if note:
            n = _request("POST", f"/lead/{urllib.parse.quote(lid)}/note", body={"text": note})
            if n.get("ok") is False:
                return n
            results["note"] = True
        if status:
            s = _request(
                "POST",
                f"/lead/{urllib.parse.quote(lid)}/status",
                body={"status": status},
            )
            if s.get("ok") is False:
                return s
            results["lead"] = s.get("lead") or s
            return results
        results["lead"] = get_lead(lid)
        return results

    body = {
        k: payload.get(k)
        for k in (
            "name", "phone", "email", "interest", "source", "budget",
            "address", "service_plan", "service_next",
        )
        if payload.get(k)
    }
    body.setdefault("source", "eve")
    created = _request("POST", "/lead", body=body, auth=False)
    if not created.get("ok"):
        return created
    new_id = str(created.get("id") or "")
    if note and new_id:
        _request("POST", f"/lead/{urllib.parse.quote(new_id)}/note", body={"text": note})
    if status and new_id:
        _request("POST", f"/lead/{urllib.parse.quote(new_id)}/status", body={"status": status})
    lead = get_lead(new_id) if new_id else created
    return {"ok": True, "lead_id": new_id, "created": True, "lead": lead}


def save_quote(payload: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for k in (
        "lead_id", "name", "phone", "email", "address", "total", "summary",
        "lines", "mode", "source", "pdf_ref", "local_quote_id", "interest",
    ):
        if payload.get(k) not in (None, ""):
            body[k] = payload[k]
    body.setdefault("source", "eve")
    return _request("POST", "/quote", body=body)


def list_jobs(*, status: str | None = None, lead_id: str | None = None) -> dict[str, Any]:
    lid = (lead_id or "").strip()
    if lid:
        return _request("GET", f"/lead/{urllib.parse.quote(lid)}/jobs")
    path = "/jobs"
    if status:
        path += "?" + urllib.parse.urlencode({"status": status})
    return _request("GET", path)


def start_job(lead_id: str, *, title: str | None = None) -> dict[str, Any]:
    lid = (lead_id or "").strip()
    if not lid:
        return {"ok": False, "error": "lead_id required"}
    body: dict[str, Any] = {}
    if title:
        body["title"] = title
    return _request("POST", f"/lead/{urllib.parse.quote(lid)}/job", body=body)


def list_customers(*, query: str | None = None) -> dict[str, Any]:
    out = _request("GET", "/api/customers")
    if out.get("error") and not out.get("ok", True):
        return out
    customers = list(out.get("customers") or [])
    q = (query or "").strip().lower()
    if q:
        customers = [
            c for c in customers
            if q in " ".join(str(c.get(k) or "") for k in ("name", "phone", "email", "id")).lower()
        ]
    return {"ok": True, "count": len(customers), "customers": customers}
