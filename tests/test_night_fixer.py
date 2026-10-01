"""Night fixer tests — the Critic-to-dispatch seam's deterministic cousin.

Pins: failing-test parsing (per-file dedupe), denylist, open-task dedupe,
per-night cap, and the wake-up note shape. The runner is injected so tests
never invoke real pytest.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from night_fixer import NightFixer  # noqa: E402

PYTEST_OUT = """
tests/test_docs_consistency.py::test_a PASSED
tests/test_alpha.py F.....
tests/test_beta.py E...
tests/test_gamma.py ..
FAILED tests/test_alpha.py::test_one - AssertionError
FAILED tests/test_alpha.py::test_two - AssertionError
FAILED tests/test_beta.py::test_engine - ValueError
FAILED tests/test_beta.py::test_parser - ValueError
2 failed, 4 passed in 1.0s
"""


@dataclass
class Task:
    id: str
    status: str
    objective: str


@dataclass
class FakeStore:
    tasks: list = field(default_factory=list)
    created: list = field(default_factory=list)

    def list_tasks(self, *, status=None):
        return tuple(self.tasks)

    def create_task(self, **kw):
        self.created.append(kw)
        return f"tid-{len(self.created)}"


@dataclass
class FakeInbox:
    notes: list = field(default_factory=list)

    def __call__(self, **kw):
        self.notes.append(kw)


def _fixer(store, inbox, pytest_out=PYTEST_OUT, **kw):
    return NightFixer(
        store=store,
        run_pytest=lambda: pytest_out,
        dispatch=lambda **k: store.create_task(**k),
        append_note=inbox,
        **kw,
    )


def test_parses_failed_files_deduped():
    files = NightFixer.failing_tests(PYTEST_OUT)
    assert files == ["tests/test_alpha.py", "tests/test_beta.py"]


def test_dispatches_templated_task_with_red_before_green_acceptance():
    store, inbox = FakeStore(), FakeInbox()
    result = _fixer(store, inbox).run()
    assert len(store.created) == 2
    first = store.created[0]
    assert first["dispatched_by"] == "night-fixer"
    assert "Make tests/test_alpha.py pass" in first["objective"]
    assert "Do NOT weaken or delete assertions" in first["objective"]
    assert first["acceptance"] == "python -m pytest tests/test_alpha.py -q"
    assert result["dispatched"] and "tid-" in result["dispatched"][0]


def test_open_task_blocks_duplicate_dispatch():
    store = FakeStore(tasks=[Task(
        id="x", status="in_review",
        objective="Make tests/test_alpha.py pass. It failed in the nightly run.",
    )])
    inbox = FakeInbox()
    result = _fixer(store, inbox).run()
    assert [c["objective"] for c in store.created] == [
        c for c in [store.created[0]["objective"]]
    ]  # only beta dispatched
    assert "tests/test_alpha.py" in result["skipped_open"]


def test_cap_limits_per_night():
    store, inbox = FakeStore(), FakeInbox()
    out = PYTEST_OUT + "\nFAILED tests/test_delta.py::test_x\nFAILED tests/test_epsilon.py::test_y"
    result = _fixer(store, inbox, pytest_out=out, max_per_night=2).run()
    assert len(store.created) == 2
    assert "tests/test_gamma.py" not in [c["objective"] for c in store.created]


def test_denylist_skips():
    store, inbox = FakeStore(), FakeInbox()
    _fixer(store, inbox, denylist=frozenset({"tests/test_alpha.py"})).run()
    assert [c["objective"] for c in store.created][0].startswith(
        "Make tests/test_beta.py pass"
    )


def test_wakeup_note_has_dispatch_and_skip_sections():
    store = FakeStore(tasks=[Task(
        id="x", status="executing",
        objective="Make tests/test_alpha.py pass. It failed in the nightly run.",
    )])
    inbox = FakeInbox()
    _fixer(store, inbox).run()
    note = inbox.notes[0]
    assert note["automation_id"] == "night_fixer"
    assert note["status"] == "ok"
    assert "Night fixer dispatched" in note["content"]
    assert "already covered by an open task: tests/test_alpha.py" in note["content"]


def test_green_suite_writes_quiet_note():
    store, inbox = FakeStore(), FakeInbox()
    _fixer(store, inbox, pytest_out="7 passed in 1.0s").run()
    assert not store.created
    assert "nothing to fix" in inbox.notes[0]["content"]
