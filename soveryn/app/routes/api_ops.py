"""Mission Control ops API — brain switch + pytest. Localhost only."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from soveryn.app.services import ops_control

bp = Blueprint("api_ops", __name__)


def _localhost_only():
    # Trust CF / reverse-proxy only if they set X-Forwarded-For carefully.
    # For ops we require the socket peer to be loopback.
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({
            "error": {"code": "localhost_only", "message": "Ops controls require localhost"},
        }), 403
    return None


@bp.get("/api/ops/brain")
def api_ops_brain_get():
    deny = _localhost_only()
    if deny:
        return deny
    return jsonify(ops_control.brain_status()), 200


@bp.post("/api/ops/brain")
def api_ops_brain_post():
    deny = _localhost_only()
    if deny:
        return deny
    body = request.get_json(silent=True) or {}
    result = ops_control.start_brain_switch(str(body.get("brain") or ""))
    code = 200 if result.get("ok") else 400
    if result.get("error") == "busy":
        code = 409
    return jsonify(result), code


@bp.get("/api/ops/tests")
def api_ops_tests_get():
    deny = _localhost_only()
    if deny:
        return deny
    job = ops_control.job_status("tests")
    return jsonify({
        "suites": ops_control.list_test_suites(),
        "job": job.get("job"),
        "log_tail": job.get("log_tail") or "",
    }), 200


@bp.post("/api/ops/tests")
def api_ops_tests_post():
    deny = _localhost_only()
    if deny:
        return deny
    body = request.get_json(silent=True) or {}
    result = ops_control.start_tests(str(body.get("suite") or ""))
    code = 200 if result.get("ok") else 400
    if result.get("error") == "busy":
        code = 409
    return jsonify(result), code


@bp.get("/api/ops/jobs/<kind>")
def api_ops_job(kind: str):
    deny = _localhost_only()
    if deny:
        return deny
    result = ops_control.job_status(kind)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code
