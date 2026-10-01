"""PondWright CRM client — the CWG lead / quote / job pipeline.

Live book: pondwright-cwg-ops on the Spark (tunneled 127.0.0.1:8100,
https://crm.pondwright.com). Ops HTTP Basic (jon / eve). Not the old
pondwright-crm field token. Citizens do not copy leads into the lattice.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_DEFAULT_URL = "http://127.0.0.1:8100"
_OPS_ENV = Path.home() / "pondwright-cwg-ops" / ".env"
_TIMEOUT = 12


def crm_base() -> str:
    raw = (os.environ.get("SOVERYN_PONDWRIGHT_CRM_URL") or "").strip()
    return raw.rstrip("/") if raw else _DEFAULT_URL


def _parse_ops_users(raw: str) -> dict[str, str]:
    users: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        user, password = part.split(":", 1)
        users[user.strip().lower()] = password
    return users


def _ops_users_from_file() -> dict[str, str]:
    if not _OPS_ENV.is_file():
        return {}
    try:
        text = _OPS_ENV.read_text(encoding="utf-8")
    except OSError:
        return {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or not line.startswith("OPS_USERS="):
            continue
        return _parse_ops_users(line.split("=", 1)[1].strip().strip('"').strip("'"))
    return {}


def crm_basic() -> tuple[str, str] | None:
    """Eve's ops login. Env wins; else pondwright-cwg-ops/.env OPS_USERS."""
    user = (os.environ.get("SOVERYN_PONDWRIGHT_CRM_USER") or "eve").strip().lower()
    password = (os.environ.get("SOVERYN_PONDWRIGHT_CRM_PASSWORD") or "").strip()
    if password:
        return user, password
    users = _ops_users_from_file()
    if user in users:
        return user, users[user]
    if "eve" in users:
        return "eve", users["eve"]
    return None


def _failed(out: dict[str, Any]) -> bool:
    http = out.get("http")
    if isinstance(http, int) and http >= 400:
        out.setdefault("ok", False)
        if not out.get("error"):
            out["error"] = str(out.get("detail") or f"http_{http}")
        return True
    return out.get("ok") is False


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
        creds = crm_basic()
        if not creds:
            return {
                "ok": False,
                "error": "crm_auth_missing",
                "hint": "Set SOVERYN_PONDWRIGHT_CRM_PASSWORD or pondwright-cwg-ops/.env OPS_USERS",
            }
        token = base64.b64encode(f"{creds[0]}:{creds[1]}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
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
                parsed.setdefault("error", str(parsed.get("detail") or f"http_{e.code}"))
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
    ping = _request("GET", "/api/leads") if health.get("ok") else {}
    return {
        "ok": bool(health.get("ok")) and not _failed(ping) if ping else bool(health.get("ok")),
        "base": crm_base(),
        "auth_configured": crm_basic() is not None,
        "health": health,
        "auth": None if not ping else {"ok": not _failed(ping), "error": ping.get("error")},
    }


def list_leads(*, status: str | None = None, query: str | None = None, limit: int = 40) -> dict[str, Any]:
    out = _request("GET", "/api/leads")
    if _failed(out):
        return out
    leads = list(out.get("leads") or [])
    if status:
        leads = [L for L in leads if (L.get("status") or "") == status]
    q = (query or "").strip().lower()
    if q:
        def _hit(L: dict[str, Any]) -> bool:
            blob = " ".join(
                str(L.get(k) or "")
                for k in ("name", "phone", "email", "interest", "source", "id", "wants", "city")
            ).lower()
            return q in blob
        leads = [L for L in leads if _hit(L)]
    leads = leads[: max(1, min(int(limit), 100))]
    return {"ok": True, "count": len(leads), "leads": leads}


def get_lead(lead_id: str) -> dict[str, Any]:
    lid = (lead_id or "").strip()
    if not lid:
        return {"ok": False, "error": "lead_id required"}
    out = _request("GET", f"/api/leads/{urllib.parse.quote(lid)}")
    if _failed(out):
        return out
    lead = out.get("lead") if isinstance(out.get("lead"), dict) else out
    lead = dict(lead)
    lead.setdefault("ok", True)
    lead.setdefault("id", lid)
    return lead


def save_lead(payload: dict[str, Any]) -> dict[str, Any]:
    lid = str(payload.get("lead_id") or "").strip()
    note = str(payload.get("note") or "").strip()
    status = str(payload.get("status") or "").strip()
    if lid:
        patch: dict[str, Any] = {}
        for k in ("name", "phone", "email", "address", "city", "interest", "wants"):
            if payload.get(k):
                patch[k] = payload[k]
        if note:
            current = get_lead(lid)
            if _failed(current):
                return current
            prior = (current.get("message") or "").rstrip()
            patch["message"] = (prior + "\n" + note).strip() if prior else note
        if status:
            patch["status"] = "contacted" if status == "service" else status
        if not patch:
            lead = get_lead(lid)
            return {"ok": not _failed(lead), "lead_id": lid, "lead": lead}
        out = _request("PATCH", f"/api/leads/{urllib.parse.quote(lid)}", body=patch)
        if _failed(out):
            return out
        lead = out.get("lead") or get_lead(lid)
        return {"ok": True, "lead_id": lid, "lead": lead}

    body = {
        k: payload.get(k)
        for k in (
            "name", "phone", "email", "interest", "source", "budget",
            "address", "city", "wants", "message",
        )
        if payload.get(k)
    }
    if note:
        body["message"] = note
    body.setdefault("source", "eve")
    created = _request("POST", "/api/leads", body=body)
    if _failed(created):
        return created
    lead = created.get("lead") or created
    new_id = str((lead or {}).get("id") or created.get("id") or "")
    if status and new_id:
        patched = _request(
            "PATCH",
            f"/api/leads/{urllib.parse.quote(new_id)}",
            body={"status": "contacted" if status == "service" else status},
        )
        if not _failed(patched):
            lead = patched.get("lead") or lead
    return {"ok": True, "lead_id": new_id, "created": True, "lead": lead}


def save_quote(payload: dict[str, Any]) -> dict[str, Any]:
    lid = str(payload.get("lead_id") or "").strip()
    if not lid:
        created = save_lead(
            {
                k: payload[k]
                for k in ("name", "phone", "email", "address", "interest", "source")
                if payload.get(k)
            }
        )
        if _failed(created):
            return created
        lid = str(created.get("lead_id") or "")
        if not lid:
            return {"ok": False, "error": "lead_create_failed"}
    lead = get_lead(lid)
    if _failed(lead):
        return lead
    job_id = str(lead.get("job_id") or "").strip()
    if not job_id:
        conv = _request("POST", f"/api/leads/{urllib.parse.quote(lid)}/convert", body={})
        if _failed(conv):
            return conv
        job = conv.get("job") or {}
        job_id = str(job.get("id") or "")
    if not job_id:
        return {"ok": False, "error": "convert_failed", "lead_id": lid}
    quote: dict[str, Any] = {}
    if payload.get("lines"):
        quote["lines"] = payload["lines"]
    if payload.get("summary"):
        quote["summary"] = payload["summary"]
    body: dict[str, Any] = {"kind": "manual", "quote": quote}
    if payload.get("total") not in (None, ""):
        body["total"] = payload["total"]
    if payload.get("mode"):
        body["estimator_mode"] = payload["mode"]
    out = _request("POST", f"/api/jobs/{urllib.parse.quote(job_id)}/quote", body=body)
    if _failed(out):
        return out
    out.setdefault("ok", True)
    out["lead_id"] = lid
    out["job_id"] = job_id
    return out


def list_jobs(*, status: str | None = None, lead_id: str | None = None) -> dict[str, Any]:
    out = _request("GET", "/api/jobs")
    if _failed(out):
        return out
    jobs = list(out.get("jobs") or [])
    lid = (lead_id or "").strip()
    if lid:
        jobs = [j for j in jobs if str(j.get("lead_id") or "") == lid]
    if status:
        jobs = [j for j in jobs if (j.get("status") or "") == status]
    return {"ok": True, "count": len(jobs), "jobs": jobs}


def start_job(lead_id: str, *, title: str | None = None) -> dict[str, Any]:
    lid = (lead_id or "").strip()
    if not lid:
        return {"ok": False, "error": "lead_id required"}
    body: dict[str, Any] = {}
    if title:
        body["title"] = title
    out = _request("POST", f"/api/leads/{urllib.parse.quote(lid)}/convert", body=body)
    if _failed(out):
        return out
    out.setdefault("ok", True)
    return out


def list_customers(*, query: str | None = None) -> dict[str, Any]:
    out = _request("GET", "/api/customers")
    if _failed(out):
        return out
    customers = list(out.get("customers") or [])
    q = (query or "").strip().lower()
    if q:
        customers = [
            c for c in customers
            if q in " ".join(str(c.get(k) or "") for k in ("name", "phone", "email", "id")).lower()
        ]
    return {"ok": True, "count": len(customers), "customers": customers}
