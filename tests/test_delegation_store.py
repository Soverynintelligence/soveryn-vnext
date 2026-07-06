import pytest
from soveryn.platform.delegation.store import DelegationStore, IllegalTransition

def _s(tmp_path): return DelegationStore(tmp_path / "deleg.db")

def test_create_defaults_to_dispatched(tmp_path):
    s = _s(tmp_path)
    tid = s.create_task(dispatched_by="aetheria", objective="add docstring",
                        scope="soveryn/x.py", acceptance="pytest tests/test_x.py")
    t = s.get_task(tid)
    assert t.status == "dispatched" and t.dispatched_by == "aetheria"
    assert t.objective == "add docstring" and t.acceptance == "pytest tests/test_x.py"

def test_status_transitions_legal_and_illegal(tmp_path):
    s = _s(tmp_path); tid = s.create_task(dispatched_by="aetheria", objective="o", scope="s", acceptance="a")
    assert s.set_status(tid, "executing") is True
    assert s.set_status(tid, "in_review") is True
    assert s.set_status(tid, "landed") is True
    with pytest.raises(IllegalTransition):
        s.set_status(tid, "executing")  # can't go backwards from landed

def test_dispatched_can_fail(tmp_path):
    s = _s(tmp_path); tid = s.create_task(dispatched_by="aetheria", objective="o", scope="s", acceptance="a")
    assert s.set_status(tid, "failed") is True

def test_set_execution_and_result_and_review(tmp_path):
    s = _s(tmp_path); tid = s.create_task(dispatched_by="aetheria", objective="o", scope="s", acceptance="a")
    s.set_status(tid, "executing")
    s.set_execution(tid, worktree_path="/tmp/wt", branch="task/abc")
    s.set_result(tid, diff="--- a\n+++ b", test_output="1 passed", summary="did the thing")
    s.set_status(tid, "in_review")
    s.set_status(tid, "rejected"); s.set_review(tid, review_feedback="wrong file")
    t = s.get_task(tid)
    assert t.branch == "task/abc" and t.diff.startswith("---") and t.review_feedback == "wrong file"

def test_list_by_status(tmp_path):
    s = _s(tmp_path)
    a = s.create_task(dispatched_by="aetheria", objective="a", scope="s", acceptance="x")
    b = s.create_task(dispatched_by="aetheria", objective="b", scope="s", acceptance="x")
    s.set_status(b, "executing"); s.set_status(b, "in_review")
    ids = [t.id for t in s.list_tasks(status="in_review")]
    assert ids == [b] and a not in ids

def test_intermediate_illegal_transitions_blocked(tmp_path):
    s = _s(tmp_path)
    tid = s.create_task(dispatched_by="aetheria", objective="o", scope="s", acceptance="a")
    with pytest.raises(IllegalTransition):
        s.set_status(tid, "in_review")   # skipped executing
    tid2 = s.create_task(dispatched_by="aetheria", objective="o", scope="s", acceptance="a")
    s.set_status(tid2, "executing")
    with pytest.raises(IllegalTransition):
        s.set_status(tid2, "landed")     # skipped in_review
