"""Web Push subscribe API for Messages PWA."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("api_push", __name__)


@bp.get("/api/push/vapid-public-key")
def vapid_public_key():
    try:
        from soveryn.platform.webpush.keys import get_vapid_public_key

        return jsonify({"publicKey": get_vapid_public_key()}), 200
    except Exception as exc:
        logger.exception("vapid public key")
        return jsonify({"error": {"code": "vapid_unavailable", "message": str(exc)}}), 503


@bp.post("/api/push/subscribe")
def subscribe():
    body = request.get_json(silent=True) or {}
    endpoint = (body.get("endpoint") or "").strip()
    keys = body.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        return jsonify({
            "error": {
                "code": "invalid_subscription",
                "message": "endpoint + keys.p256dh + keys.auth required",
            }
        }), 400
    try:
        from soveryn.platform.webpush import store as push_store

        push_store.upsert_subscription(
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=(request.headers.get("User-Agent") or "")[:240],
        )
        return jsonify({"ok": True}), 200
    except Exception as exc:
        logger.exception("push subscribe")
        return jsonify({"error": {"code": "subscribe_failed", "message": str(exc)}}), 500


@bp.post("/api/push/unsubscribe")
def unsubscribe():
    body = request.get_json(silent=True) or {}
    endpoint = (body.get("endpoint") or "").strip()
    if not endpoint:
        return jsonify({
            "error": {"code": "invalid_subscription", "message": "endpoint required"}
        }), 400
    from soveryn.platform.webpush import store as push_store

    removed = push_store.remove_subscription(endpoint)
    return jsonify({"ok": True, "removed": removed}), 200


@bp.get("/api/push/status")
def status():
    """Local/operator: how many phones are subscribed."""
    from soveryn.platform.webpush import store as push_store

    rows = push_store.list_subscriptions()
    return jsonify({
        "subscriptions": len(rows),
        "endpoints": [r["endpoint"][-48:] for r in rows],
    }), 200


@bp.post("/api/push/test")
def test_push():
    """Localhost smoke — send a test needs-you notification."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"error": {"code": "forbidden", "message": "localhost only"}}), 403
    from soveryn.platform.webpush.notify import notify_needs_you

    notify_needs_you(
        title="SOVERYN test",
        body="Push is wired — open Messages",
        url="/messages",
        tag="soveryn-test",
    )
    return jsonify({"ok": True, "queued": True}), 200
