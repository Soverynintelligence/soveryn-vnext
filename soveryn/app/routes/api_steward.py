"""SOVERYN vNext — /api/steward/* read-only grant-compliance endpoints."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, current_app, jsonify, request

from soveryn.platform.steward.engine import compute_grant_schedule
from soveryn.platform.steward.store import load_grants

bp = Blueprint("api_steward", __name__)


@bp.get("/api/steward/board")
def api_steward_board():
    """Return upcoming + overdue grant obligations, sorted by due_date.

    Optional query param:
        ?days=N  — horizon in days (default 400). Lookback is fixed at 365.

    Response shape:
        {
          "as_of": "YYYY-MM-DD",
          "config_present": true,
          "entries": [
            {
              "award_id": str,
              "funder": str,
              "label": str,
              "due_date": "YYYY-MM-DD",
              "days_out": int,   # negative = overdue
              "status": "upcoming" | "overdue",
              "amount": float | null
            },
            ...
          ]
        }

    Graceful: FileNotFoundError on missing grants.json returns 200 with
    config_present=false and entries=[] — never 500.
    Done obligations are excluded (board shows open items only).
    """
    try:
        horizon_days = int(request.args.get("days", 400))
    except (TypeError, ValueError):
        horizon_days = 400

    env = current_app.extensions["soveryn"]["env"]
    grants_path = env.data_root / "steward" / "grants.json"
    today = date.today()

    try:
        grants = load_grants(str(grants_path))
    except FileNotFoundError:
        return jsonify({
            "as_of": today.isoformat(),
            "config_present": False,
            "entries": [],
        }), 200

    obligations = compute_grant_schedule(
        grants,
        today=today,
        lookback_days=365,
        horizon_days=horizon_days,
    )

    # Build a lookup so we can surface award_amount on each entry.
    # GrantObligation intentionally omits it (engine is cadence-only),
    # so we join back to the source Grant by award_id.
    amount_by_id = {g.award_id: g.award_amount for g in grants}

    entries = []
    for ob in obligations:
        if ob.status == "done":
            continue
        days_out = (ob.due_date - today).days
        entries.append({
            "award_id": ob.award_id,
            "funder": ob.funder,
            "label": ob.report_label,
            "due_date": ob.due_date.isoformat(),
            "days_out": days_out,
            "status": ob.status,
            "amount": amount_by_id.get(ob.award_id),
        })

    return jsonify({
        "as_of": today.isoformat(),
        "config_present": True,
        "entries": entries,
    }), 200
