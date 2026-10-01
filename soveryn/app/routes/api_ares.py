"""SOVERYN vNext — /api/ares/* — Ares findings surface for Mission Control.

Ares publishes an append-only event log (findings flap active<->cleared) to
ares_bus.sqlite3. This exposes the CURRENT active state: the latest event per
finding key, active only, grouped by severity. Read-only GET is best-effort —
a missing/locked DB or malformed row yields an empty result, never a 500.

POST /api/ares/findings/clear (localhost only) appends human-cleared events so
Mission Control can dismiss emergencies/criticals that are known or stale.
If Ares re-detects a finding as *new* later, it will reappear on the bus.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, abort, current_app, jsonify, request

bp = Blueprint("api_ares", __name__)

_DEFAULT_BUS = Path.home() / "soveryn_vnext" / "data" / "ares" / "ares_bus.sqlite3"
_SEV_ORDER = {"emergency": 0, "critical": 1, "warning": 2}
_LOCALHOST_ADDRS = {"127.0.0.1", "::1"}

# latest event per finding key (payload.$.id), newest event id wins
_QUERY = """
SELECT payload, created_at FROM (
    SELECT payload, created_at,
           ROW_NUMBER() OVER (
               PARTITION BY json_extract(payload, '$.id') ORDER BY id DESC) AS rn
    FROM events
    WHERE json_valid(payload))   -- skip malformed rows BEFORE json_extract aborts the statement
WHERE rn = 1
"""


def read_active_findings(bus_path: str) -> dict:
    result = {
        "findings": [],
        "counts": {"emergency": 0, "critical": 0, "warning": 0},
        "generated_at": None,
    }
    if not os.path.exists(bus_path):
        return result
    try:
        conn = sqlite3.connect(f"file:{bus_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(_QUERY).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return result

    findings = []
    for r in rows:
        try:
            p = json.loads(r["payload"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(p, dict) or p.get("status") != "active":
            continue
        sev = p.get("severity")
        if sev not in _SEV_ORDER:
            continue
        ev = p.get("evidence")
        ev_str = ev if isinstance(ev, str) else json.dumps(ev)
        findings.append({
            "severity": sev,
            "finding_type": p.get("finding_type", ""),
            "key": p.get("id", ""),
            "evidence": (ev_str or "")[:120],
            "last_seen": r["created_at"],
        })
        result["counts"][sev] += 1

    # Two stable sorts: newest-first within each severity, then group by severity.
    # ISO-8601 strings sort lexically, so reverse=True on last_seen == newest-first.
    findings.sort(key=lambda f: f["last_seen"] or "", reverse=True)
    findings.sort(key=lambda f: _SEV_ORDER[f["severity"]])
    result["findings"] = findings
    return result


def clear_findings(
    bus_path: str,
    *,
    keys: list[str] | None = None,
    severities: list[str] | None = None,
    reason: str = "human_clear",
) -> dict[str, Any]:
    """Append status=cleared events for matching *currently active* findings.

    Selection (OR within each list; AND across lists when both provided):
      keys — exact finding ids (payload.id)
      severities — emergency / critical / warning

    If only severities is set, all active findings at those severities clear.
    If only keys is set, those keys clear when active.
    If both empty, nothing is cleared (caller should pass intentional filters).

    Returns counts and the list of keys cleared. Missing DB → error dict.
    """
    if not os.path.exists(bus_path):
        return {"ok": False, "error": "ares bus not found", "cleared": [], "count": 0}

    active = read_active_findings(bus_path)["findings"]
    key_set = {k for k in (keys or []) if k}
    sev_set = {s.lower().strip() for s in (severities or []) if s}
    for s in sev_set:
        if s not in _SEV_ORDER:
            return {
                "ok": False,
                "error": f"unknown severity: {s}",
                "cleared": [],
                "count": 0,
            }

    if not key_set and not sev_set:
        return {
            "ok": False,
            "error": "provide keys and/or severities",
            "cleared": [],
            "count": 0,
        }

    targets = []
    for f in active:
        key_ok = (not key_set) or (f["key"] in key_set)
        sev_ok = (not sev_set) or (f["severity"] in sev_set)
        if key_ok and sev_ok:
            targets.append(f)

    if not targets:
        return {"ok": True, "cleared": [], "count": 0, "message": "nothing matched"}

    now = datetime.now(timezone.utc).isoformat()
    note = (reason or "human_clear").strip()[:200] or "human_clear"
    try:
        conn = sqlite3.connect(bus_path)
        try:
            for f in targets:
                # Preserve original evidence when possible; wrap with clear note.
                try:
                    evidence: Any = json.loads(f["evidence"]) if f.get("evidence") else {}
                except (json.JSONDecodeError, TypeError):
                    evidence = {"prior": f.get("evidence") or ""}
                if not isinstance(evidence, dict):
                    evidence = {"prior": evidence}
                evidence = {
                    **evidence,
                    "cleared_by": "human",
                    "clear_reason": note,
                    "cleared_at": now,
                }
                payload = {
                    "id": f["key"],
                    "finding_type": f.get("finding_type") or "",
                    "severity": f["severity"],
                    "evidence": evidence,
                    "status": "cleared",
                }
                conn.execute(
                    "INSERT INTO events (event_type, payload, actor, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        "anomaly.detected",
                        json.dumps(payload, separators=(",", ":")),
                        "human",
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"bus write failed: {exc}", "cleared": [], "count": 0}

    cleared_keys = [f["key"] for f in targets]
    return {
        "ok": True,
        "cleared": cleared_keys,
        "count": len(cleared_keys),
        "reason": note,
        "at": now,
    }


def _ares_bus_path() -> str:
    override = current_app.config.get("ARES_BUS_PATH")
    return str(override) if override else str(_DEFAULT_BUS)


def _require_localhost() -> None:
    if request.remote_addr not in _LOCALHOST_ADDRS:
        abort(403, description="ares write endpoints require localhost")


@bp.get("/api/ares/findings")
def api_ares_findings():
    data = read_active_findings(_ares_bus_path())
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    return jsonify(data), 200


@bp.post("/api/ares/findings/clear")
def api_ares_clear_findings():
    """Dismiss active findings by key and/or severity. Localhost only.

    Body JSON:
      keys: string[]          — finding ids to clear
      severities: string[]    — e.g. ["emergency","critical"]
      reason: string          — optional note stored on the clear event
    """
    _require_localhost()
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        abort(400, description="JSON object required")

    keys = body.get("keys")
    severities = body.get("severities")
    if keys is not None and not isinstance(keys, list):
        abort(400, description="keys must be a list")
    if severities is not None and not isinstance(severities, list):
        abort(400, description="severities must be a list")

    result = clear_findings(
        _ares_bus_path(),
        keys=[str(k) for k in keys] if keys else None,
        severities=[str(s) for s in severities] if severities else None,
        reason=str(body.get("reason") or "human_clear"),
    )
    status = 200 if result.get("ok") else 400
    # Always refresh active view for the client
    result["active"] = read_active_findings(_ares_bus_path())
    result["active"]["generated_at"] = datetime.now(timezone.utc).isoformat()
    return jsonify(result), status
