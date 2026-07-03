"""SOVERYN vNext — /api/ares/* — Ares findings surface for Mission Control.

Ares publishes an append-only event log (findings flap active<->cleared) to
ares_bus.sqlite3. This exposes the CURRENT active state: the latest event per
finding key, active only, grouped by severity. Read-only, best-effort — a
missing/locked DB or malformed row yields an empty result, never a 500.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify

bp = Blueprint("api_ares", __name__)

_DEFAULT_BUS = Path.home() / "soveryn_vnext" / "data" / "ares" / "ares_bus.sqlite3"
_SEV_ORDER = {"emergency": 0, "critical": 1, "warning": 2}

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


def _ares_bus_path() -> str:
    override = current_app.config.get("ARES_BUS_PATH")
    return str(override) if override else str(_DEFAULT_BUS)


@bp.get("/api/ares/findings")
def api_ares_findings():
    data = read_active_findings(_ares_bus_path())
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    return jsonify(data), 200
