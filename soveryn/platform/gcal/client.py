"""Google Calendar client — CWG events for Eve. No passwords."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from soveryn.platform.gcal.config import GcalConfig, load_config
from soveryn.platform.gcal.oauth import GcalAuthError, get_access_token

HttpFn = Callable[..., dict[str, Any]]

EVENTS_TMPL = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events"
EVENT_TMPL = "https://www.googleapis.com/calendar/v3/calendars/{cal}/events/{eid}"
_DONE_MARK = "[DONE]"


class GcalError(RuntimeError):
    def __init__(self, message: str, *, status: str = "error", http_status: int = 0):
        super().__init__(message)
        self.status = status
        self.http_status = http_status


def _default_http(
    url: str,
    *,
    method: str = "GET",
    token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:800]
        if e.code in (401, 403):
            raise GcalError(
                "Google Calendar session expired or Calendar API is not enabled. "
                "Jon re-runs `python -m soveryn.platform.gcal authorize` "
                "and enables Calendar API on the Cloud project.",
                status="needs_login",
                http_status=e.code,
            ) from e
        raise GcalError(
            f"Calendar HTTP {e.code}: {err}", status="error", http_status=e.code
        ) from e


def _cwg_status(item: dict[str, Any]) -> str:
    priv = ((item.get("extendedProperties") or {}).get("private") or {})
    if str(priv.get("cwgStatus") or "").lower() == "done":
        return "done"
    title = str(item.get("summary") or "")
    if title.upper().startswith(_DONE_MARK):
        return "done"
    return "open"


def _fail(status: str, message: str, **extra: Any) -> dict[str, Any]:
    out = {"ok": False, "status": status, "message": message}
    out.update(extra)
    return out


def gcal_status(cfg: GcalConfig | None = None) -> dict[str, Any]:
    c = cfg or load_config()
    oauth_ready = c.configured and c.authorized
    return {
        "ok": True,
        "configured": c.configured or c.ical_configured,
        "authorized": oauth_ready,
        "ical": c.ical_configured,
        "calendar_id": c.calendar_id,
        "timezone": c.timezone,
        "token_path": str(c.token_path),
        "needs_oauth_client": not c.configured and not c.ical_configured,
        "needs_login": c.configured and not c.authorized and not c.ical_configured,
        "read_via": "oauth" if oauth_ready else ("ical" if c.ical_configured else "none"),
    }


def _parse_when(raw: str, tz_name: str) -> datetime:
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def list_events(
    *,
    days: int = 7,
    days_back: int = 7,
    max_results: int = 15,
    query: str = "",
    cfg: GcalConfig | None = None,
    token: str | None = None,
    http: HttpFn = _default_http,
    now: datetime | None = None,
) -> dict[str, Any]:
    c = cfg or load_config()
    days = max(1, min(int(days), 31))
    days_back = max(0, min(int(days_back), 31))
    max_results = max(1, min(int(max_results), 40))
    tz = ZoneInfo(c.timezone)
    origin = (now or datetime.now(tz)).astimezone(tz)
    start = origin - timedelta(days=days_back)
    end = origin + timedelta(days=days)
    use_oauth = bool(c.authorized or token is not None)
    if not use_oauth and c.ical_configured:
        return _list_via_ical(
            c, start=start, end=end, max_results=max_results, query=query
        )
    if not c.configured:
        return _fail(
            "needs_oauth_client",
            "Set SOVERYN_GBP_CLIENT_ID / SOVERYN_GBP_CLIENT_SECRET, "
            "or SOVERYN_GCAL_ICAL_URL for read-only.",
        )
    if not c.authorized and token is None:
        return _fail(
            "needs_login",
            "Jon runs `python -m soveryn.platform.gcal authorize`, "
            "or set SOVERYN_GCAL_ICAL_URL for read-only.",
        )
    cal = urllib.parse.quote(c.calendar_id, safe="")
    params = {
        "timeMin": _rfc3339(start),
        "timeMax": _rfc3339(end),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(max_results),
    }
    if query.strip():
        params["q"] = query.strip()
    url = f"{EVENTS_TMPL.format(cal=cal)}?{urllib.parse.urlencode(params)}"
    try:
        tok = token if token is not None else get_access_token(c)
        payload = http(url, method="GET", token=tok)
    except GcalAuthError as e:
        return _fail("needs_login", str(e))
    except GcalError as e:
        return _fail(e.status, str(e), http_status=e.http_status)
    items = payload.get("items") or []
    events = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start_block = item.get("start") or {}
        end_block = item.get("end") or {}
        events.append(
            {
                "id": item.get("id"),
                "summary": item.get("summary") or "(no title)",
                "start": start_block.get("dateTime") or start_block.get("date"),
                "end": end_block.get("dateTime") or end_block.get("date"),
                "location": item.get("location") or "",
                "html_link": item.get("htmlLink") or "",
                "cwg_status": _cwg_status(item),
            }
        )
    return {
        "ok": True,
        "status": "ok",
        "calendar_id": c.calendar_id,
        "timezone": c.timezone,
        "from": _rfc3339(start),
        "to": _rfc3339(end),
        "count": len(events),
        "events": events,
        "via": "oauth",
    }


def _unfold_ics(text: str) -> str:
    return text.replace("\r\n ", "").replace("\n ", "").replace("\r\n", "\n")


def _ics_unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _parse_ics_dt(raw: str, tz_name: str) -> datetime | None:
    s = raw.strip()
    tz = ZoneInfo(tz_name)
    utc = s.endswith("Z")
    if utc:
        s = s[:-1]
    if "T" in s:
        for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.replace(tzinfo=timezone.utc if utc else tz)
            except ValueError:
                continue
        return None
    if s.isdigit() and len(s) == 8:
        try:
            return datetime.strptime(s, "%Y%m%d").replace(tzinfo=tz)
        except ValueError:
            return None
    return None


def _parse_ics_events(text: str, *, tz_name: str) -> list[dict[str, Any]]:
    blocks = _unfold_ics(text).split("BEGIN:VEVENT")
    out: list[dict[str, Any]] = []
    for block in blocks[1:]:
        fields: dict[str, str] = {}
        for line in block.split("\n"):
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            name = key.split(";", 1)[0].upper()
            if name in {"SUMMARY", "LOCATION", "UID", "DTSTART", "DTEND"}:
                fields[name] = _ics_unescape(val.strip())
        start = _parse_ics_dt(fields.get("DTSTART") or "", tz_name)
        end = _parse_ics_dt(fields.get("DTEND") or "", tz_name)
        if start is None:
            continue
        out.append(
            {
                "id": fields.get("UID") or "",
                "summary": fields.get("SUMMARY") or "(no title)",
                "start": start.isoformat(),
                "end": end.isoformat() if end else "",
                "location": fields.get("LOCATION") or "",
                "html_link": "",
            }
        )
    out.sort(key=lambda e: e["start"])
    return out


def _list_via_ical(
    cfg: GcalConfig,
    *,
    start: datetime,
    end: datetime,
    max_results: int,
    query: str,
) -> dict[str, Any]:
    req = urllib.request.Request(
        cfg.ical_url,
        headers={"User-Agent": "soveryn-vnext/0 (+local)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as e:
        return _fail("error", f"iCal fetch failed: {type(e).__name__}")
    events = []
    q = query.strip().lower()
    for ev in _parse_ics_events(raw, tz_name=cfg.timezone):
        try:
            when = datetime.fromisoformat(ev["start"])
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=ZoneInfo(cfg.timezone))
        if when < start or when > end:
            continue
        if q and q not in (ev["summary"] + " " + ev["location"]).lower():
            continue
        events.append(ev)
        if len(events) >= max_results:
            break
    return {
        "ok": True,
        "status": "ok",
        "calendar_id": "ical",
        "timezone": cfg.timezone,
        "from": _rfc3339(start),
        "to": _rfc3339(end),
        "count": len(events),
        "events": events,
        "via": "ical",
    }


def complete_event(
    *,
    event_id: str,
    cfg: GcalConfig | None = None,
    token: str | None = None,
    http: HttpFn = _default_http,
) -> dict[str, Any]:
    """Mark a CWG job done on the calendar (PATCH). Does not delete it."""
    c = cfg or load_config()
    eid = (event_id or "").strip()
    if not eid:
        return _fail("error", "event_id is required")
    if not c.configured:
        return _fail(
            "needs_oauth_client",
            "Set SOVERYN_GBP_CLIENT_ID / SOVERYN_GBP_CLIENT_SECRET.",
        )
    if not c.authorized and token is None:
        return _fail(
            "needs_login",
            "Jon runs `python -m soveryn.platform.gcal authorize`.",
        )
    cal = urllib.parse.quote(c.calendar_id, safe="")
    eid_q = urllib.parse.quote(eid, safe="")
    url = EVENT_TMPL.format(cal=cal, eid=eid_q)
    try:
        tok = token if token is not None else get_access_token(c)
        current = http(url, method="GET", token=tok)
        title = str(current.get("summary") or "").strip() or "(no title)"
        if not title.upper().startswith(_DONE_MARK):
            title = f"{_DONE_MARK} {title}"
        body = {
            "summary": title,
            "colorId": "8",
            "extendedProperties": {"private": {"cwgStatus": "done"}},
        }
        payload = http(url, method="PATCH", token=tok, body=body)
    except GcalAuthError as e:
        return _fail("needs_login", str(e))
    except GcalError as e:
        return _fail(e.status, str(e), http_status=e.http_status)
    return {
        "ok": True,
        "status": "done",
        "id": payload.get("id") or eid,
        "summary": payload.get("summary") or title,
        "cwg_status": "done",
        "html_link": payload.get("htmlLink") or "",
    }


def create_event(
    *,
    summary: str,
    start: str,
    end: str = "",
    location: str = "",
    description: str = "",
    cfg: GcalConfig | None = None,
    token: str | None = None,
    http: HttpFn = _default_http,
) -> dict[str, Any]:
    c = cfg or load_config()
    if not c.configured:
        return _fail(
            "needs_oauth_client",
            "Set SOVERYN_GBP_CLIENT_ID / SOVERYN_GBP_CLIENT_SECRET.",
        )
    if not c.authorized and token is None:
        return _fail(
            "needs_login",
            "Jon runs `python -m soveryn.platform.gcal authorize`.",
        )
    title = (summary or "").strip()
    if not title:
        return _fail("error", "summary is required")
    try:
        start_dt = _parse_when(start, c.timezone)
    except ValueError:
        return _fail("error", "start must be ISO-8601 (e.g. 2026-09-08T10:00)")
    if end.strip():
        try:
            end_dt = _parse_when(end, c.timezone)
        except ValueError:
            return _fail("error", "end must be ISO-8601")
    else:
        end_dt = start_dt + timedelta(hours=1)
    body: dict[str, Any] = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": c.timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": c.timezone},
    }
    if location.strip():
        body["location"] = location.strip()
    if description.strip():
        body["description"] = description.strip()
    cal = urllib.parse.quote(c.calendar_id, safe="")
    url = EVENTS_TMPL.format(cal=cal)
    try:
        tok = token if token is not None else get_access_token(c)
        payload = http(url, method="POST", token=tok, body=body)
    except GcalAuthError as e:
        return _fail("needs_login", str(e))
    except GcalError as e:
        return _fail(e.status, str(e), http_status=e.http_status)
    return {
        "ok": True,
        "status": "created",
        "id": payload.get("id"),
        "summary": payload.get("summary") or title,
        "html_link": payload.get("htmlLink") or "",
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }
