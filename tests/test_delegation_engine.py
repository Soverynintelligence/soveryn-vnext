"""Tests for soveryn.platform.delegation.engine.execute_task.

Uses a real DelegationStore (tmp_path SQLite) and fully injected fakes for all
git/Scotty seams — no real worktrees, no network.
"""
from __future__ import annotations

import pytest

from soveryn.platform.delegation.store import DelegationStore
from soveryn.platform.delegation.engine import execute_task


# ─── Helpers / Fakes ─────────────────────────────────────────────────────────

def _store(tmp_path) -> DelegationStore:
    return DelegationStore(tmp_path / "deleg.db")


def _task(store: DelegationStore, *, objective="add docstring", scope="soveryn/x.py",
          acceptance="pytest tests/test_x.py") -> str:
    return store.create_task(
        dispatched_by="aetheria",
        objective=objective,
        scope=scope,
        acceptance=acceptance,
    )


def _fake_make_worktree(worktree_path: str = "/tmp/fake-wt", branch: str = "task/fake"):
    """Returns an injectable make_worktree that records its calls."""
    calls: list[tuple] = []

    def make_worktree(repo_root, task_id):
        calls.append((repo_root, task_id))
        return worktree_path, branch

    make_worktree.calls = calls  # type: ignore[attr-defined]
    return make_worktree


def _fake_remove_worktree():
    """Returns an injectable remove_worktree that records calls without side effects."""
    calls: list[tuple] = []

    def remove_worktree(repo_root, worktree_path, branch):
        calls.append((repo_root, worktree_path, branch))

    remove_worktree.calls = calls  # type: ignore[attr-defined]
    return remove_worktree


def _fake_scotty_run(summary: str = "done"):
    calls: list[tuple] = []

    def scotty_run(worktree_path, objective, scope, acceptance=""):
        # acceptance added 2026-07-27: Scotty is now TOLD the criterion he
        # is judged on. Withholding it was why 10/10 real tasks failed.
        calls.append((worktree_path, objective, scope, acceptance))
        return summary

    scotty_run.calls = calls  # type: ignore[attr-defined]
    return scotty_run


def _fake_diff_fn(diff: str = "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new"):
    calls: list[str] = []

    def diff_fn(worktree_path):
        calls.append(worktree_path)
        return diff

    diff_fn.calls = calls  # type: ignore[attr-defined]
    return diff_fn


def _fake_run_acceptance(passed: bool = True, output: str = "1 passed",
                         baseline_passed: bool = False):
    """Injectable acceptance runner modelling red-before-green.

    The engine now runs acceptance TWICE: once on the pristine worktree to prove
    the command can fail, then again after Scotty. So the first call is the
    baseline and defaults to RED — which is what a well-formed task looks like,
    since a test that already passes cannot judge new work.

    Pass baseline_passed=True to simulate the vacuous case (2026-07-28: an
    acceptance naming a pre-existing suite that covered none of the task).
    """
    calls: list[tuple] = []

    def run_acceptance(worktree_path, acceptance):
        first = not calls
        calls.append((worktree_path, acceptance))
        if first:
            return baseline_passed, ("1 passed" if baseline_passed else "1 failed")
        return passed, output

    run_acceptance.calls = calls  # type: ignore[attr-defined]
    return run_acceptance


def _fake_commit_fn():
    calls: list[tuple] = []

    def commit_fn(worktree_path, branch, message):
        calls.append((worktree_path, branch, message))

    commit_fn.calls = calls  # type: ignore[attr-defined]
    return commit_fn


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestGreenPath:
    """Acceptance tests pass → task ends in_review with all data stored."""

    def test_final_status_is_in_review(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=True),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
        )

        assert store.get_task(tid).status == "in_review"

    def test_result_fields_stored(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)
        diff = "--- a\n+++ b"
        summary = "added the docstring"
        output = "2 passed"

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(summary=summary),
            run_acceptance=_fake_run_acceptance(passed=True, output=output),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(diff=diff),
            commit_fn=_fake_commit_fn(),
        )

        t = store.get_task(tid)
        assert t.diff == diff
        assert t.test_output == output
        assert t.summary == summary

    def test_commit_fn_called_on_green(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store, objective="my-objective")
        commit = _fake_commit_fn()

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=True),
            make_worktree=_fake_make_worktree(branch="task/mybranch"),
            diff_fn=_fake_diff_fn(),
            commit_fn=commit,
        )

        assert len(commit.calls) == 1
        wt, branch, message = commit.calls[0]
        assert branch == "task/mybranch"
        assert tid in message

    def test_execution_stored_worktree_and_branch(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)
        wt_path = "/tmp/my-wt-path"
        branch = "task/abc123"

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=True),
            make_worktree=_fake_make_worktree(worktree_path=wt_path, branch=branch),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
        )

        t = store.get_task(tid)
        assert t.worktree_path == wt_path
        assert t.branch == branch

    def test_worktree_retained_on_green(self, tmp_path):
        """On success the worktree must NOT be removed (approve-time merge needs it)."""
        store = _store(tmp_path)
        tid = _task(store)
        remove = _fake_remove_worktree()

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=True),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
            remove_worktree=remove,
        )

        assert len(remove.calls) == 0

    def test_status_sequence_executing_then_in_review(self, tmp_path):
        """Verify the status goes dispatched → executing → in_review (no skip)."""
        store = _store(tmp_path)
        tid = _task(store)

        # Status starts at dispatched
        assert store.get_task(tid).status == "dispatched"

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=True),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
        )

        # If we got to in_review, the executing → in_review transition fired
        # (the store guards it — if executing was skipped it would have raised)
        assert store.get_task(tid).status == "in_review"


class TestRedPath:
    """Acceptance tests fail → task ends failed; diff+output still recorded; no commit."""

    def test_final_status_is_failed(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=False, output="FAILED"),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
        )

        assert store.get_task(tid).status == "failed"

    def test_diff_and_output_still_recorded_on_red(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)
        diff = "--- a\n+++ b"
        output = "FAILED assertion"

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=False, output=output),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(diff=diff),
            commit_fn=_fake_commit_fn(),
        )

        t = store.get_task(tid)
        assert t.diff == diff
        assert t.test_output == output
        assert t.summary == "acceptance tests failed"

    def test_commit_fn_not_called_on_red(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)
        commit = _fake_commit_fn()

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=False),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=commit,
        )

        assert len(commit.calls) == 0

    def test_no_in_review_on_red(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=False),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
        )

        # in_review must never appear
        assert store.get_task(tid).status == "failed"

    def test_worktree_retained_on_red(self, tmp_path):
        """CHANGED 2026-07-22: on failure the worktree is RETAINED for forensic
        inspection, not removed. With a single failed task nothing is beyond the
        retention window, so remove_worktree is not called. (Was
        test_worktree_removed_on_red, which asserted the delete-on-failure
        behavior that made the Scotty 8/8 failures undiagnosable.)"""
        store = _store(tmp_path)
        tid = _task(store)
        remove = _fake_remove_worktree()

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=False),
            make_worktree=_fake_make_worktree(worktree_path="/tmp/fake-wt", branch="task/fake"),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
            remove_worktree=remove,
        )

        assert not remove.calls


class TestExceptionHandling:
    """Any exception → task lands in failed; nothing escapes execute_task."""

    def test_scotty_run_raises_task_fails(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)

        def boom_scotty(wt, obj, scope):
            raise RuntimeError("scotty exploded")

        # Must not propagate
        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=boom_scotty,
            run_acceptance=_fake_run_acceptance(passed=True),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
            remove_worktree=_fake_remove_worktree(),  # hermetic — no real git
        )

        assert store.get_task(tid).status == "failed"

    def test_set_status_executing_failure_lands_failed(self, tmp_path):
        # If the first transition (->executing) fails, the task must NOT be
        # stranded in 'dispatched' — best-effort land it in 'failed'.
        store = _store(tmp_path)
        tid = _task(store)
        real_set = store.set_status
        calls: list[str] = []

        def flaky(task_id, status):
            calls.append(status)
            if status == "executing":
                raise RuntimeError("db hiccup on executing")
            return real_set(task_id, status)

        store.set_status = flaky  # type: ignore[method-assign]
        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=True),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
            remove_worktree=_fake_remove_worktree(),
        )
        assert store.get_task(tid).status == "failed"   # not stranded
        assert calls == ["executing", "failed"]         # tried, fell back

    def test_scotty_run_raises_no_exception_escapes(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)

        def boom_scotty(wt, obj, scope):
            raise ValueError("fatal")

        # execute_task itself must NOT raise
        try:
            execute_task(
                tid,
                store=store,
                repo_root="/fake/repo",
                scotty_run=boom_scotty,
                run_acceptance=_fake_run_acceptance(),
                make_worktree=_fake_make_worktree(),
                diff_fn=_fake_diff_fn(),
                commit_fn=_fake_commit_fn(),
            )
        except Exception as exc:
            pytest.fail(f"execute_task raised unexpectedly: {exc}")

    def test_run_acceptance_raises_task_fails(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)

        def boom_accept(wt, acceptance):
            raise RuntimeError("acceptance tool crashed")

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=boom_accept,
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
        )

        assert store.get_task(tid).status == "failed"

    def test_make_worktree_raises_task_fails(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)

        def boom_wt(repo_root, task_id):
            raise OSError("no disk space")

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(),
            make_worktree=boom_wt,
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
        )

        assert store.get_task(tid).status == "failed"

    def test_worktree_retained_on_exception(self, tmp_path):
        """CHANGED 2026-07-22: an exception mid-flow RETAINS the worktree (only
        forensic record) rather than deleting it, and the exception is still
        swallowed — execute_task never propagates. With one failed task nothing
        is pruned."""
        store = _store(tmp_path)
        tid = _task(store)
        remove = _fake_remove_worktree()

        def boom_scotty(wt, obj, scope):
            raise RuntimeError("boom")

        # must not raise
        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=boom_scotty,
            run_acceptance=_fake_run_acceptance(),
            make_worktree=_fake_make_worktree(worktree_path="/tmp/fake-wt", branch="task/fake"),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
            remove_worktree=remove,
        )

        assert store.get_task(tid).status == "failed"
        assert not remove.calls


# ─── Forensic evidence retention (added 2026-07-22) ──────────────────────────
# Root cause of the Scotty 8/8 empty-diff failures went undiagnosed for 6 weeks
# because failure DELETED the worktree and the exception path captured NO diff.
# These pin: (a) a raised scotty_run still records whatever diff exists, and
# (b) failed worktrees are RETAINED for inspection, not cleaned up.

class TestForensicRetention:
    def test_exception_path_captures_diff_before_any_cleanup(self, tmp_path):
        """A task whose scotty_run RAISES (e.g. tool_round_limit) must still
        store the diff of whatever landed in the worktree — otherwise the
        failure is invisible."""
        store = _store(tmp_path)
        tid = _task(store)
        diff = _fake_diff_fn(diff="--- a\n+++ b\n@@ +partial work@@")

        def boom(worktree_path, objective, scope):
            raise RuntimeError("tool_round_limit: budget exhausted")

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=boom,
            run_acceptance=_fake_run_acceptance(),
            make_worktree=_fake_make_worktree(),
            diff_fn=diff,
            commit_fn=_fake_commit_fn(),
            remove_worktree=_fake_remove_worktree(),
        )

        task = store.get_task(tid)
        assert task.status == "failed"
        # diff_fn was consulted even though scotty_run raised
        assert diff.calls, "diff must be captured on the exception path"

    def test_failed_worktree_is_retained_not_removed(self, tmp_path):
        """Red acceptance must NOT delete the worktree — it's the only forensic
        record of what Scotty actually did."""
        store = _store(tmp_path)
        tid = _task(store)
        remover = _fake_remove_worktree()

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=_fake_run_acceptance(passed=False, output="0 passed"),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
            remove_worktree=remover,
        )

        assert store.get_task(tid).status == "failed"
        assert not remover.calls, "failed worktree must be retained for inspection"

    def test_prunes_worktrees_beyond_retention_cap(self, tmp_path, monkeypatch):
        """Retention is bounded: once more than FAILED_WORKTREE_RETENTION tasks
        have failed, the oldest worktrees are pruned so disk does not grow
        without limit."""
        import soveryn.platform.delegation.engine as eng
        monkeypatch.setattr(eng, "FAILED_WORKTREE_RETENTION", 2)

        store = _store(tmp_path)
        made = []

        # A REALISTIC remover: actually deletes the dir, like the real
        # remove_worktree. This matters — the engine skips pruning a worktree
        # whose path no longer exists, so a non-deleting fake would re-prune the
        # same dirs every round and over-count.
        remove_calls: list[tuple] = []

        def remove(repo_root, worktree_path, branch):
            remove_calls.append((repo_root, worktree_path, branch))
            import shutil
            shutil.rmtree(worktree_path, ignore_errors=True)

        remove.calls = remove_calls  # type: ignore[attr-defined]

        def make_wt(repo_root, task_id):
            p = tmp_path / f"wt-{task_id}"
            p.mkdir()
            made.append(str(p))
            return str(p), f"task/{task_id}"

        for _ in range(4):
            tid = _task(store)
            eng.execute_task(
                tid, store=store, repo_root="/fake/repo",
                scotty_run=_fake_scotty_run(),
                run_acceptance=_fake_run_acceptance(passed=False),
                make_worktree=make_wt,
                diff_fn=_fake_diff_fn(), commit_fn=_fake_commit_fn(),
                remove_worktree=remove,
            )

        # 4 failed, retention=2 → the 2 oldest should have been pruned
        assert len(remove.calls) == 2, remove.calls
        pruned_paths = {c[1] for c in remove.calls}
        assert pruned_paths == set(made[:2]), "the two OLDEST worktrees should be pruned"


class TestAcceptanceIsToldToScotty:
    """Scotty must be TOLD the criterion he is judged on.

    2026-07-27: every delegation task ever dispatched — 10 of 10 — failed. The
    engine ran `run_acceptance(worktree, task.acceptance)` but called
    `scotty_run(worktree, objective, scope)` without it. Scotty was graded on a
    rubric he was never shown. Two failure signatures followed: "acceptance
    tests failed" (built the wrong shape) and "execution raised before
    acceptance" (burned the round budget working out what done meant).
    """

    def test_acceptance_reaches_the_runner(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store, acceptance="pytest tests/test_greeting.py")
        fake = _fake_scotty_run()

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=fake,
            run_acceptance=_fake_run_acceptance(passed=True),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
        )

        assert fake.calls, "scotty_run was never called"
        assert fake.calls[0][3] == "pytest tests/test_greeting.py", (
            "Scotty was not told the acceptance command. He is judged by it, so "
            "withholding it makes the task unwinnable by construction."
        )


class TestVacuousAcceptanceIsRefused:
    """An acceptance that passes before any work cannot judge the work.

    2026-07-28: a real dispatch named tests/test_active_context.py as its
    acceptance — a 320-line suite covering code merged that same morning, which
    referenced nothing the task asked for. Scotty wrote 142 lines, the
    pre-existing tests passed, and the task reached in_review having tested none
    of it. The mirror of the 07-27 defect: that acceptance could never pass,
    this one could never fail. Both because nothing checked the gate was related
    to the task.
    """

    def test_task_fails_when_acceptance_passes_on_pristine_worktree(self, tmp_path):
        store = _store(tmp_path)
        tid = _task(store)
        scotty = _fake_scotty_run()

        execute_task(
            tid,
            store=store,
            repo_root="/fake/repo",
            scotty_run=scotty,
            run_acceptance=_fake_run_acceptance(baseline_passed=True),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(),
            commit_fn=_fake_commit_fn(),
        )

        task = store.get_task(tid)
        assert task.status == "failed"
        assert "vacuous" in (task.summary or "").lower()

    def test_scotty_is_never_started_on_a_vacuous_acceptance(self, tmp_path):
        """Don't burn a model run on a gate that cannot judge the result."""
        store = _store(tmp_path)
        tid = _task(store)
        scotty = _fake_scotty_run()

        execute_task(
            tid, store=store, repo_root="/fake/repo",
            scotty_run=scotty,
            run_acceptance=_fake_run_acceptance(baseline_passed=True),
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(), commit_fn=_fake_commit_fn(),
        )

        assert not scotty.calls, "Scotty ran despite an unjudgeable acceptance"

    def test_red_baseline_then_green_still_reaches_in_review(self, tmp_path):
        """The normal path: fails before the work, passes after."""
        store = _store(tmp_path)
        tid = _task(store)
        results = iter([(False, "1 failed"), (True, "1 passed")])

        def run_acceptance(worktree, acceptance):
            return next(results)

        execute_task(
            tid, store=store, repo_root="/fake/repo",
            scotty_run=_fake_scotty_run(),
            run_acceptance=run_acceptance,
            make_worktree=_fake_make_worktree(),
            diff_fn=_fake_diff_fn(), commit_fn=_fake_commit_fn(),
        )

        assert store.get_task(tid).status == "in_review"
