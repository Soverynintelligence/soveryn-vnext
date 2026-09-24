"""Staged X posts — the surface that lets Jon actually see and answer one.

Why this exists
---------------
Until 2026-07-28 a staged post had no reader anywhere. No route listed staged
posts, no template rendered them, no tool let Aetheria check for one, and the
audit tool did not cover the store. The ONLY approval path was a pre-turn hook
that classified whatever Jon happened to type next to her as affirm or decline.

The result, from data/x_staged.db: five consecutive daily posts staged between
07-22 and 07-27, every one of them `expired`, none seen. She wrote them
correctly and believed she had; there was simply no channel.

Design notes
------------
* Reuses ``publish_staged`` / ``reject_staged`` — the same code the chat
  classifier runs. A button must not be a second, subtly different publish path.
* Best-effort reads: a listing endpoint that 500s is a listing endpoint that
  gets removed from the panel. It returns [] instead.
* Writes are NOT best-effort. Approving is publishing to a live public account;
  a failure there must surface loudly rather than report success.
* Clearing the action from the live thread happens on BOTH outcomes, so
  "actions she has not heard back on" stops being true the moment it stops
  being true.
"""
from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("x_approvals", __name__)

def _ext() -> dict:
    return current_app.extensions.get("soveryn") or {}


def _post_to_dict(post) -> dict:
    return {
        "id": post.id,
        "agent": post.agent,
        "text": post.text,
        "reply_to": post.reply_to or "",
        "proposed_at": post.proposed_at,
        "state": post.state,
    }


def _clear_action() -> None:
    """Drop the staged-post marker from the cross-rail live thread."""
    svc = _ext().get("active_context")
    if svc is None:
        return
    try:
        svc.clear_action("x_post_staged")
    except Exception:
        logger.exception("could not clear x_post_staged from active context")


@bp.get("/api/x/staged")
def x_staged_pending():
    """Return the pending staged post, or []. Never 500."""
    try:
        staged = _ext().get("x_staged")
        if staged is None:
            return jsonify([]), 200
        posts = staged.pending_all()
        return jsonify([_post_to_dict(p) for p in posts]), 200
    except Exception:
        logger.exception("x_staged_pending: unexpected error; returning []")
        return jsonify([]), 200


@bp.post("/api/x/staged/<post_id>/approve")
def x_staged_approve(post_id: str):
    """Publish the staged post to X. Deliberately NOT best-effort."""
    ext = _ext()
    staged = ext.get("x_staged")
    publisher_fn = ext.get("x_publisher_fn")
    x_memory_fn = ext.get("x_memory_fn")
    if staged is None or publisher_fn is None or x_memory_fn is None:
        return jsonify({"error": "x presence is not wired"}), 503

    post = staged.get(post_id)
    if post is None or post.state != "proposed":
        return jsonify({"error": "no staged post pending"}), 404

    from soveryn.agents.presence.resolver import publish_staged
    result = publish_staged(
        post=post, staged=staged, publisher_fn=publisher_fn,
        x_memory_fn=x_memory_fn,
    )
    if result.action != "published":
        # publish_staged leaves the post `proposed` on failure so it can retry.
        return jsonify({"error": result.note, "state": "proposed"}), 502

    _clear_action()
    return jsonify({
        "status": "published",
        "note": result.note,
        "posted_id": result.posted_id,
    }), 200


@bp.post("/api/x/staged/<post_id>/reject")
def x_staged_reject(post_id: str):
    """Drop the staged post. Reason is optional and is logged for her."""
    ext = _ext()
    staged = ext.get("x_staged")
    rejection_fn = ext.get("x_rejection_fn")
    if staged is None or rejection_fn is None:
        return jsonify({"error": "x presence is not wired"}), 503

    post = staged.get(post_id)
    if post is None or post.state != "proposed":
        return jsonify({"error": "no staged post pending"}), 404

    reason = ""
    if request.is_json:
        reason = (request.get_json(silent=True) or {}).get("reason", "") or ""

    from soveryn.agents.presence.resolver import reject_staged
    reject_staged(post=post, staged=staged, rejection_fn=rejection_fn,
                  reason=reason)
    _clear_action()
    return jsonify({"status": "rejected"}), 200
