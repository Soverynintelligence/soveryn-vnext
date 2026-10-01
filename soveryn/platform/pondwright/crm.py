"""PondWright CRM client — the CWG lead / quote / job pipeline.

Live book: pondwright-cwg-ops on the Spark (tunneled 127.0.0.1:8100,
https://crm.pondwright.com). Ops HTTP Basic (jon / eve). Not the old
pondwright-crm field token. Citizens do not copy leads into the lattice.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_DEFAULT_URL = "http://127.0.0.1:8100"
_OPS_ENV = Path.home() / "pondwright-cwg-ops" / ".env"
_TIMEOUT = 12

# Pick-lists mirrored from pondwright-cwg-ops app/main.py (LEAD_JOB_TYPES and
# LEAD_SOURCES, 2026-10-01). The CRM is the source of truth: it rejects a new
# lead without name + phone/email + job_type + source (HTTP 422) and merges a
# repeat phone/email into the existing lead. Keep these in step with the CRM.
LEAD_JOB_TYPES: tuple[str, ...] = (
    "Swim pond", "New pond build", "Waterfall/stream", "Remodel/rebuild", "Repair",
    "Cleanout", "Green water", "Maintenance plan", "Other",
)
LEAD_SOURCES: tuple[str, ...] = (
    "Website/Google search", "Google profile", "Facebook", "Instagram", "Nextdoor",
    "Yelp", "Referral", "Repeat customer", "Other", "Phone/text unknown",
)
DEFAULT_SOURCE = "Phone/text unknown"  # Jon told Eve, but not how they found CWG
_SOURCE_LEGACY = {
    "website": "Website/Google search",
    "repeat": "Repeat customer",
    "eve": DEFAULT_SOURCE,
}
# First match wins (same order as the CRM's own inference).
_JOB_TYPE_KEYWORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"swim"), "Swim pond"),
    (re.compile(r"clean ?-?out"), "Cleanout"),
    (re.compile(r"green|algae|duckweed|murky"), "Green water"),
    (re.compile(r"maintenance|care plan|service plan|2x ?/ ?year|twice a year|pond check"), "Maintenance plan"),
    (re.compile(r"remodel|rebuild|renovat|\bre-?do\b"), "Remodel/rebuild"),
    (re.compile(r"repair|leak|pump|broken|not working|\bfix"), "Repair"),
    (re.compile(r"waterfall|stream|pondless"), "Waterfall/stream"),
    (re.compile(r"new pond|pond build|build (a |me a )?pond|ecosystem pond|koi pond|install"), "New pond build"),
)
_QUOTE_MODE_JOB_TYPES = {"new": "New pond build", "repair": "Repair", "maint": "Maintenance plan"}
_NO_BLANK_RETRY = (
    "Do not retry with blank or made-up fields. Tell Jon plainly what the CRM said "
    "and ask him for what is missing, then save again."
)


def pick_job_type(value: Any) -> str:
    """Exact pick-list label (case-insensitive), else ''."""
    v = str(value or "").strip().lower()
    for label in LEAD_JOB_TYPES:
        if v == label.lower():
            return label
    return ""


def infer_job_type(*texts: Any) -> str:
    """Keyword guess from what the person asked for; '' when unclear."""
    blob = " ".join(str(t or "") for t in texts).lower()
    for rx, label in _JOB_TYPE_KEYWORDS:
        if rx.search(blob):
            return label
    return ""


def pick_source(value: Any) -> str:
    """Pick-list source. Blank -> 'Phone/text unknown'. Unknown text goes to the
    CRM as-is (it maps aliases like 'nextdoor post' itself)."""
    raw = str(value or "").strip()
    if not raw:
        return DEFAULT_SOURCE
    low = raw.lower()
    for label in LEAD_SOURCES:
        if low == label.lower():
            return label
    return _SOURCE_LEGACY.get(low, raw)


def _digit_count(raw: Any) -> int:
    return sum(1 for c in str(raw or "") if c.isdigit())


def _has_contact(phone: str, email: str) -> bool:
    # Same bar as the CRM: >= 7 phone digits or an address with "@".
    return _digit_count(phone) >= 7 or "@" in (email or "")


def _http_detail(out: dict[str, Any]) -> str:
    detail = out.get("detail")
    if isinstance(detail, list):  # FastAPI validation error list
        detail = "; ".join(
            str(d.get("msg") if isinstance(d, dict) else d) for d in detail if d
        )
    return str(detail or out.get("error") or f"http_{out.get('http')}").strip()


def _rejected(out: dict[str, Any]) -> dict[str, Any]:
    detail = _http_detail(out)
    return {
        "ok": False,
        "saved": False,
        "rejected": True,
        "http": out.get("http"),
        "error": detail,
        "message": f"CRM rejected: {detail}",
        "instruction": _NO_BLANK_RETRY,
    }


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
        if payload.get("job_type"):
            jt = pick_job_type(payload["job_type"]) or infer_job_type(payload["job_type"])
            if jt:
                patch["job_type"] = jt
        if payload.get("source"):
            patch["source"] = pick_source(payload["source"])
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
        if out.get("http") == 422:
            return _rejected(out)
        if _failed(out):
            return out
        lead = out.get("lead") or get_lead(lid)
        return {"ok": True, "lead_id": lid, "lead": lead}
    return _create_lead(payload, note=note, status=status)


def _create_lead(payload: dict[str, Any], *, note: str, status: str) -> dict[str, Any]:
    """New person -> POST /api/leads. Checks the CRM's rules first so Eve asks
    Jon instead of sending blanks; reports 422s and merges in plain words."""
    name = str(payload.get("name") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    email = str(payload.get("email") or "").strip()
    if not name:
        return {
            "ok": False, "saved": False, "needs": "name", "error": "missing_name",
            "message": "Not saved: no name. Ask Jon who this is (one person per save).",
        }
    if not _has_contact(phone, email):
        return {
            "ok": False, "saved": False, "needs": "phone_or_email",
            "error": f"Need phone or email for {name}",
            "message": (
                f"Not saved: no phone or email for {name}. Ask Jon for {name}'s "
                "phone number or email, then save again. Do not save with blanks."
            ),
        }
    job_type = pick_job_type(payload.get("job_type")) or infer_job_type(
        payload.get("job_type"), payload.get("interest"), payload.get("wants"),
        payload.get("message"), note,
    )
    if not job_type:
        return {
            "ok": False, "saved": False, "needs": "job_type",
            "error": f"Need job type for {name}",
            "message": (
                f"Not saved: I can't tell what job {name} wants. Ask Jon what the job is "
                f"({', '.join(LEAD_JOB_TYPES)}), then save again with job_type."
            ),
        }
    source = pick_source(payload.get("source"))
    body: dict[str, Any] = {
        k: payload.get(k)
        for k in ("interest", "budget", "address", "city", "wants", "message")
        if payload.get(k)
    }
    body.update({"name": name, "job_type": job_type, "source": source})
    if phone:
        body["phone"] = phone
    if email:
        body["email"] = email
    if note:
        body["message"] = note
    created = _request("POST", "/api/leads", body=body)
    if created.get("http") == 422:
        return _rejected(created)
    if _failed(created):
        return created
    lead = created.get("lead") if isinstance(created.get("lead"), dict) else {}
    new_id = str(created.get("id") or lead.get("id") or "")
    if created.get("merged"):
        shown = str(lead.get("name") or name)
        out: dict[str, Any] = {
            "ok": True, "merged": True, "created": False, "lead_id": new_id, "lead": lead,
            "message": f"Already in CRM as {shown} (id {new_id}); added your note to the existing lead.",
        }
        if status:
            out["status_note"] = (
                f"Status not changed (existing lead is {lead.get('status') or 'unknown'}). "
                "Ask Jon, then set it with lead_id."
            )
        return out
    if status and new_id:
        patched = _request(
            "PATCH",
            f"/api/leads/{urllib.parse.quote(new_id)}",
            body={"status": "contacted" if status == "service" else status},
        )
        if not _failed(patched):
            lead = patched.get("lead") or lead
    return {
        "ok": True, "created": True, "merged": False, "lead_id": new_id,
        "job_type": job_type, "source": source, "lead": lead,
        "message": f"Saved {name} to the CRM as a new lead ({job_type}; source {source}).",
    }


def save_quote(payload: dict[str, Any]) -> dict[str, Any]:
    lid = str(payload.get("lead_id") or "").strip()
    if not lid:
        create_args = {
            k: payload[k]
            for k in ("name", "phone", "email", "address", "interest", "source", "job_type")
            if payload.get(k)
        }
        if not create_args.get("job_type"):
            mode_type = _QUOTE_MODE_JOB_TYPES.get(str(payload.get("mode") or "").strip().lower())
            if mode_type:
                create_args["job_type"] = mode_type
        if not create_args.get("interest") and payload.get("summary"):
            create_args["interest"] = payload["summary"]
        created = save_lead(create_args)
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
