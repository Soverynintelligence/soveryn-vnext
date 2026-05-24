"""SOVERYN vNext — health/status endpoint."""

from __future__ import annotations
from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    state = current_app.extensions["soveryn"]
    payload = {
        "app": "soveryn",
        "version": current_app.config["SOVERYN_VERSION"],
        "active_agents": sorted(state["agent_loops"].keys()),
    }
    if request.args.get("preflight") == "1":
        # Lazy import: preflight does network probes; skip unless asked.
        from soveryn.app.preflight import run_preflight
        report = run_preflight(env=state["env"])
        payload["preflight"] = {
            "ok": report.ok,
            "n_ok":       sum(1 for r in report.results if r.status == "ok"),
            "n_fail":     sum(1 for r in report.results if r.status == "fail"),
            "n_deferred": sum(1 for r in report.results if r.status == "deferred"),
            "failures": [
                {"name": r.name, "kind": r.kind, "detail": r.detail}
                for r in report.failures
            ],
        }
    return jsonify(payload), 200
