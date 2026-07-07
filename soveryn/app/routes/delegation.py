"""SOVERYN vNext — /api/delegation/* — human review/approval gate.

Nothing lands without an explicit human action.

Routes
------
GET  /api/delegation/pending
    Return all tasks in status ``in_review`` as a JSON list. Best-effort —
    never 500, returns [] on any error.

POST /api/delegation/<task_id>/approve
    Merge the task's branch into the main repo. On success → status
    ``landed`` + worktree cleanup + ``{ok:true, status:"landed", restart_hint}``.
    On merge conflict → 409 ``{ok:false, message}``; status stays ``in_review``,
    worktree is NOT removed so the branch survives for retry.

POST /api/delegation/<task_id>/reject
    Record review feedback + transition to ``rejected`` + remove worktree.
    Returns ``{ok:true, status:"rejected"}``.

Injection
---------
The store and git helpers are read from ``current_app.extensions["soveryn"]``
under the keys ``delegation_store``, ``merge_fn``, ``remove_fn``, and
``repo_root``.  When a key is absent the real implementations are used as
fallback so production startup (which doesn't wire delegation keys yet) is safe.

Tests inject fakes via the extensions dict so no real git or DB is required.
"""
from __future__ import annotations

import logging
from typing import Callable

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("delegation", __name__)

_RESTART_HINT = "restart soveryn-vnext to apply"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ext() -> dict:
    """Return ``app.extensions["soveryn"]``, or an empty dict if absent."""
    return current_app.extensions.get("soveryn") or {}


def _get_store():
    """Return the injected DelegationStore, or None if not configured."""
    ext = _ext()
    store = ext.get("delegation_store")
    if store is not None:
        return store
    # Fall back to the real store when not injected (production path).
    try:
        from soveryn.platform.delegation.store import DelegationStore
        from pathlib import Path
        env = ext.get("env")
        if env is not None:
            db_path = getattr(env, "data_root", Path.home() / "soveryn_vnext" / "data") / "delegation.db"
        else:
            db_path = Path.home() / "soveryn_vnext" / "data" / "delegation.db"
        return DelegationStore(db_path)
    except Exception:
        return None


def _get_merge_fn() -> Callable:
    """Return the injected merge function, or the real worktree merge."""
    fn = _ext().get("merge_fn")
    if fn is not None:
        return fn
    from soveryn.platform.delegation.worktree import merge_worktree
    return merge_worktree


def _get_remove_fn() -> Callable:
    """Return the injected remove function, or the real worktree remove."""
    fn = _ext().get("remove_fn")
    if fn is not None:
        return fn
    from soveryn.platform.delegation.worktree import remove_worktree
    return remove_worktree


def _get_repo_root() -> str:
    """Return the injected repo root or the default vnext path."""
    root = _ext().get("repo_root")
    if root is not None:
        return str(root)
    import os
    return os.path.expanduser("~/soveryn_vnext")


def _task_to_dict(task) -> dict:
    """Serialize a Task to the public JSON shape."""
    return {
        "id": task.id,
        "objective": task.objective,
        "summary": task.summary,
        "diff": task.diff,
        "test_output": task.test_output,
        "status": task.status,
    }


# ─── Routes ───────────────────────────────────────────────────────────────────

@bp.get("/api/delegation/pending")
def delegation_pending():
    """Return all ``in_review`` tasks. Best-effort: never 500."""
    try:
        store = _get_store()
        if store is None:
            return jsonify([]), 200
        tasks = store.list_tasks(status="in_review")
        return jsonify([_task_to_dict(t) for t in tasks]), 200
    except Exception:
        logger.exception("delegation_pending: unexpected error; returning []")
        return jsonify([]), 200


@bp.post("/api/delegation/<task_id>/approve")
def delegation_approve(task_id: str):
    """Approve a task: merge its branch, mark landed, remove worktree.

    The merge conflict invariant is load-bearing:
    - A conflict MUST NOT mark the task ``landed``
    - A conflict MUST NOT remove the worktree (branch must survive for retry)
    """
    store = _get_store()
    if store is None:
        return jsonify({"ok": False, "message": "delegation store not configured"}), 503

    task = store.get_task(task_id)
    if task is None:
        return jsonify({"ok": False, "message": f"Task {task_id!r} not found"}), 404

    if task.status != "in_review":
        return jsonify({
            "ok": False,
            "message": f"Task {task_id!r} is '{task.status}', not 'in_review'; cannot approve",
        }), 409

    # Attempt the merge — this is the only operation that can proceed to landed.
    merge_fn = _get_merge_fn()
    repo_root = _get_repo_root()
    branch = task.branch or f"task/{task_id}"

    ok, msg = merge_fn(repo_root, branch)

    if not ok:
        # Conflict: leave status as in_review, do NOT remove the worktree.
        return jsonify({"ok": False, "message": msg}), 409

    # Merge succeeded — land it.
    try:
        store.set_status(task_id, "landed")
    except Exception:
        logger.exception("approve: set_status(landed) failed for %s", task_id)
        # Still attempt worktree cleanup; re-raise would leave the tree dangling.

    # Cleanup worktree after successful merge.
    worktree_path = task.worktree_path or ""
    try:
        remove_fn = _get_remove_fn()
        remove_fn(repo_root, worktree_path, branch)
    except Exception:
        logger.exception(
            "approve: remove_worktree failed for %s (non-fatal; merge already landed)",
            task_id,
        )

    return jsonify({
        "ok": True,
        "status": "landed",
        "restart_hint": _RESTART_HINT,
    }), 200


@bp.post("/api/delegation/<task_id>/reject")
def delegation_reject(task_id: str):
    """Reject a task: record feedback, mark rejected, remove worktree."""
    store = _get_store()
    if store is None:
        return jsonify({"ok": False, "message": "delegation store not configured"}), 503

    task = store.get_task(task_id)
    if task is None:
        return jsonify({"ok": False, "message": f"Task {task_id!r} not found"}), 404

    body = request.get_json(silent=True) or {}
    feedback = body.get("feedback", "")

    # Record review feedback first (best-effort).
    try:
        store.set_review(task_id, review_feedback=feedback)
    except Exception:
        logger.exception("reject: set_review failed for %s (non-fatal)", task_id)

    # Transition status.
    try:
        store.set_status(task_id, "rejected")
    except Exception:
        logger.exception("reject: set_status(rejected) failed for %s", task_id)

    # Remove worktree (best-effort — rejected work is gone, but don't block response).
    repo_root = _get_repo_root()
    branch = task.branch or f"task/{task_id}"
    worktree_path = task.worktree_path or ""
    try:
        remove_fn = _get_remove_fn()
        remove_fn(repo_root, worktree_path, branch)
    except Exception:
        logger.exception(
            "reject: remove_worktree failed for %s (non-fatal)", task_id,
        )

    return jsonify({"ok": True, "status": "rejected"}), 200
