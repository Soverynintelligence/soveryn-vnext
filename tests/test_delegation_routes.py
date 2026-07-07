"""Tests for /api/delegation/* — human review/approval gate.

Uses a minimal Flask app with the delegation blueprint injected directly,
plus a fake DelegationStore, fake merge_fn, and fake remove_fn — no real git,
no real DB, no full create_app dependency chain.
"""
from __future__ import annotations

import pytest
from flask import Flask

from soveryn.app.routes.delegation import bp
from soveryn.platform.delegation.store import DelegationStore


# ─── Fake store ───────────────────────────────────────────────────────────────

class FakeTask:
    """Minimal Task-like object for injection."""
    def __init__(self, **kwargs):
        self.id = kwargs["id"]
        self.objective = kwargs.get("objective", "Fix the bug")
        self.summary = kwargs.get("summary", "Changed foo.py")
        self.diff = kwargs.get("diff", "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new")
        self.test_output = kwargs.get("test_output", "1 passed")
        self.status = kwargs.get("status", "in_review")
        self.branch = kwargs.get("branch", f"task/{self.id}")
        self.worktree_path = kwargs.get("worktree_path", f"/tmp/wt/{self.id}")
        self.review_feedback = kwargs.get("review_feedback", None)


class FakeStore:
    def __init__(self, tasks: list[FakeTask]):
        self._tasks = {t.id: t for t in tasks}
        self._status_calls: list[tuple[str, str]] = []
        self._review_calls: list[tuple[str, str]] = []

    def list_tasks(self, *, status: str | None = None) -> tuple:
        results = list(self._tasks.values())
        if status is not None:
            results = [t for t in results if t.status == status]
        return tuple(results)

    def get_task(self, task_id: str):
        return self._tasks.get(task_id)

    def set_status(self, task_id: str, status: str) -> bool:
        self._status_calls.append((task_id, status))
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.status = status
        return True

    def set_review(self, task_id: str, *, review_feedback: str) -> bool:
        self._review_calls.append((task_id, review_feedback))
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.review_feedback = review_feedback
        return True


# ─── App factory ─────────────────────────────────────────────────────────────

def _make_app(
    tasks: list[FakeTask],
    merge_result: tuple[bool, str] = (True, "Merge made by the 'no-ff' strategy."),
):
    """Build a minimal Flask app with the delegation blueprint + injected fakes."""
    store = FakeStore(tasks)
    merge_calls: list[tuple] = []
    remove_calls: list[tuple] = []

    def fake_merge(repo_root, branch):
        merge_calls.append((repo_root, branch))
        return merge_result

    def fake_remove(repo_root, worktree_path, branch):
        remove_calls.append((repo_root, worktree_path, branch))

    app = Flask("test_delegation")
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    app.config["TESTING"] = True
    app.extensions["soveryn"] = {
        "delegation_store": store,
        "merge_fn": fake_merge,
        "remove_fn": fake_remove,
        "repo_root": "/fake/repo",
    }
    app.register_blueprint(bp)

    # Attach the call-capture lists to the app for test assertions
    app._test_store = store
    app._test_merge_calls = merge_calls
    app._test_remove_calls = remove_calls

    return app


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def in_review_task():
    return FakeTask(id="task-abc", status="in_review")


@pytest.fixture
def executing_task():
    return FakeTask(id="task-xyz", status="executing")


@pytest.fixture
def client_green(in_review_task):
    """App where merge always succeeds."""
    app = _make_app(
        tasks=[in_review_task],
        merge_result=(True, "Merged"),
    )
    with app.test_client() as c:
        yield c, app


@pytest.fixture
def client_conflict(in_review_task):
    """App where merge always conflicts."""
    app = _make_app(
        tasks=[in_review_task],
        merge_result=(False, "CONFLICT (content): Merge conflict in foo.py"),
    )
    with app.test_client() as c:
        yield c, app


@pytest.fixture
def client_wrong_status(executing_task):
    """App with a task that is NOT in_review."""
    app = _make_app(
        tasks=[executing_task],
        merge_result=(True, "Merged"),
    )
    with app.test_client() as c:
        yield c, app


@pytest.fixture
def client_multi(in_review_task, executing_task):
    """App with multiple tasks in different statuses."""
    app = _make_app(
        tasks=[in_review_task, executing_task],
        merge_result=(True, "Merged"),
    )
    with app.test_client() as c:
        yield c, app


# ─── /api/delegation/pending ─────────────────────────────────────────────────

class TestPending:
    def test_returns_only_in_review_tasks(self, client_multi):
        client, app = client_multi
        resp = client.get("/api/delegation/pending")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "task-abc"
        assert data[0]["status"] == "in_review"

    def test_shape_includes_required_fields(self, client_green):
        client, app = client_green
        resp = client.get("/api/delegation/pending")
        assert resp.status_code == 200
        item = resp.get_json()[0]
        for field in ("id", "objective", "summary", "diff", "test_output", "status"):
            assert field in item, f"Missing field: {field}"

    def test_empty_when_no_in_review(self, client_wrong_status):
        client, app = client_wrong_status
        resp = client.get("/api/delegation/pending")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_never_500(self, client_green):
        """Best-effort: even a broken store should not 500."""
        client, app = client_green
        # Simulate a broken store by monkey-patching
        app.extensions["soveryn"]["delegation_store"] = None
        resp = client.get("/api/delegation/pending")
        assert resp.status_code == 200
        assert resp.get_json() == []


# ─── /api/delegation/<id>/approve ────────────────────────────────────────────

class TestApprove:
    def test_green_path_returns_landed(self, client_green):
        client, app = client_green
        resp = client.post("/api/delegation/task-abc/approve")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["status"] == "landed"
        assert "restart_hint" in data
        assert "restart" in data["restart_hint"].lower() or "soveryn" in data["restart_hint"].lower()

    def test_green_path_calls_merge(self, client_green):
        client, app = client_green
        client.post("/api/delegation/task-abc/approve")
        assert len(app._test_merge_calls) == 1
        _repo_root, branch = app._test_merge_calls[0]
        assert branch == "task/task-abc"

    def test_green_path_calls_remove(self, client_green):
        client, app = client_green
        client.post("/api/delegation/task-abc/approve")
        assert len(app._test_remove_calls) == 1

    def test_green_path_sets_status_landed(self, client_green):
        client, app = client_green
        client.post("/api/delegation/task-abc/approve")
        store = app._test_store
        assert store.get_task("task-abc").status == "landed"

    def test_conflict_returns_409(self, client_conflict):
        client, app = client_conflict
        resp = client.post("/api/delegation/task-abc/approve")
        assert resp.status_code == 409
        data = resp.get_json()
        assert data["ok"] is False
        assert "message" in data

    def test_conflict_status_stays_in_review(self, client_conflict):
        client, app = client_conflict
        client.post("/api/delegation/task-abc/approve")
        store = app._test_store
        assert store.get_task("task-abc").status == "in_review"

    def test_conflict_does_not_call_remove(self, client_conflict):
        """On conflict: worktree must NOT be removed so the branch survives for retry."""
        client, app = client_conflict
        client.post("/api/delegation/task-abc/approve")
        assert len(app._test_remove_calls) == 0

    def test_conflict_does_not_call_remove_and_not_landed(self, client_conflict):
        """Double-check: neither landed nor removed."""
        client, app = client_conflict
        client.post("/api/delegation/task-abc/approve")
        assert len(app._test_remove_calls) == 0
        assert app._test_store.get_task("task-abc").status == "in_review"

    def test_wrong_status_returns_409(self, client_wrong_status):
        client, app = client_wrong_status
        resp = client.post("/api/delegation/task-xyz/approve")
        assert resp.status_code == 409
        data = resp.get_json()
        assert data["ok"] is False

    def test_wrong_status_merge_not_called(self, client_wrong_status):
        client, app = client_wrong_status
        client.post("/api/delegation/task-xyz/approve")
        assert len(app._test_merge_calls) == 0

    def test_unknown_task_approve_returns_404(self, client_green):
        client, app = client_green
        resp = client.post("/api/delegation/no-such-task/approve")
        assert resp.status_code == 404

    def test_approve_is_only_path_to_landed(self, client_conflict):
        """Reject cannot land; only approve on success can."""
        client, app = client_conflict
        # Reject the task
        client.post(
            "/api/delegation/task-abc/reject",
            json={"feedback": "Doesn't look right"},
        )
        assert app._test_store.get_task("task-abc").status == "rejected"
        # Approve (even if it were somehow re-attempted) can't reach landed via reject path


# ─── /api/delegation/<id>/reject ─────────────────────────────────────────────

class TestReject:
    def test_reject_returns_rejected(self, client_green):
        client, app = client_green
        resp = client.post(
            "/api/delegation/task-abc/reject",
            json={"feedback": "Tests pass but logic is wrong."},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["status"] == "rejected"

    def test_reject_sets_status_rejected(self, client_green):
        client, app = client_green
        client.post(
            "/api/delegation/task-abc/reject",
            json={"feedback": "Not good enough."},
        )
        store = app._test_store
        assert store.get_task("task-abc").status == "rejected"

    def test_reject_stores_feedback(self, client_green):
        client, app = client_green
        client.post(
            "/api/delegation/task-abc/reject",
            json={"feedback": "Missing edge case X."},
        )
        store = app._test_store
        # Feedback stored via set_review
        assert any(
            call[0] == "task-abc" and "Missing edge case X" in call[1]
            for call in store._review_calls
        )

    def test_reject_calls_remove(self, client_green):
        client, app = client_green
        client.post(
            "/api/delegation/task-abc/reject",
            json={"feedback": "Reject this."},
        )
        assert len(app._test_remove_calls) == 1

    def test_unknown_task_reject_returns_404(self, client_green):
        client, app = client_green
        resp = client.post(
            "/api/delegation/no-such-task/reject",
            json={"feedback": "nope"},
        )
        assert resp.status_code == 404


# ─── Review follow-up: honest-approve + reject guard ─────────────────────────

def test_approve_set_status_failure_returns_500_not_false_landed(in_review_task):
    """If recording 'landed' fails after a successful merge, approve must NOT
    claim landed (honesty), and must NOT remove the worktree."""
    app = _make_app(tasks=[in_review_task], merge_result=(True, "Merged"))
    store = app._test_store
    orig = store.set_status
    def flaky(task_id, status):
        if status == "landed":
            raise RuntimeError("db write failed")
        return orig(task_id, status)
    store.set_status = flaky
    with app.test_client() as c:
        resp = c.post("/api/delegation/task-abc/approve")
    assert resp.status_code == 500
    body = resp.get_json()
    assert body["ok"] is False and body["status"] == "unknown"
    assert app._test_remove_calls == []          # worktree left for manual check


def test_reject_non_in_review_returns_409():
    """A landed (or any non-in_review) task cannot be rejected."""
    landed = FakeTask(id="task-landed", status="landed")
    app = _make_app(tasks=[landed])
    with app.test_client() as c:
        resp = c.post("/api/delegation/task-landed/reject", json={"feedback": "no"})
    assert resp.status_code == 409
    assert resp.get_json()["ok"] is False
    assert landed.status == "landed"             # unchanged
    assert app._test_remove_calls == []
