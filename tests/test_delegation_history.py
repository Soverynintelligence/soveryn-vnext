"""She should not have to ask a question she has no way to know to ask.

Between 3 and 13 August the Graph-Native substrate was dispatched at least seven
times. Two of those were rejected with written reasons; the rest failed. Nothing
put the previous outcome in front of her at the moment she asked again, so the
loop simply repeated — and two of Jon's own rejections say so: *"already
completed! nice work aetheria had you doing loops"* and *"the slice was already
built aetheria was unaware"*.

The existing `_find_open_duplicate` guard blocks a second dispatch only while
one is LIVE. That is correct and must not change: the 2026-08-11 attempt fixed
the exact connection leak the 2026-08-07 review named, and a guard that refused
retries would have refused the correction.

So these tests pin the opposite property — the retry stays possible, and the
evidence arrives with it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from soveryn.platform.delegation.history import (
    dispatch_warning,
    prior_attempts,
    similarity,
)

SUBSTRATE = (
    "Implement the core SQLite schema for the Graph-Native Lattice substrate. "
    "Create a new file soveryn/memory/substrate.py with nodes and edges tables."
)


@dataclass
class FakeTask:
    id: str
    status: str
    objective: str
    created_at: str
    scope: str = ""
    review_feedback: str = ""


@dataclass
class FakeStore:
    tasks: list = field(default_factory=list)

    def list_tasks(self):
        return self.tasks


def test_a_reworded_repeat_of_a_rejected_objective_is_surfaced():
    """The real case: same idea, different words, different target file."""
    store = FakeStore([
        FakeTask("t1", "rejected",
                 "Implement the Graph-Native Lattice Substrate. Requirements: "
                 "nodes and edges tables in soveryn/memory/lattice_vnext.py",
                 "2026-08-07T00:00:00", scope="soveryn/memory/lattice_vnext.py",
                 review_feedback="REJECTED — connection leak, 42 fds after 200 nodes."),
    ])
    prior = prior_attempts(store, SUBSTRATE)
    assert prior, "a reworded repeat of a rejected direction was not surfaced"
    assert prior[0].status == "rejected"
    assert "connection leak" in prior[0].review_feedback


def test_unrelated_work_is_not_dragged_in():
    store = FakeStore([
        FakeTask("t1", "rejected",
                 "Implement the Cross-Rail Active Context Manager per spec",
                 "2026-07-28T00:00:00", scope="soveryn/context/service.py"),
    ])
    assert prior_attempts(store, SUBSTRATE) == []


def test_live_and_landed_work_is_not_reported_as_a_prior_failure():
    """Only closed-unhappily tasks are evidence against asking again."""
    store = FakeStore([
        FakeTask("t1", "in_review", SUBSTRATE, "2026-08-11T00:00:00"),
        FakeTask("t2", "landed", SUBSTRATE, "2026-08-01T00:00:00"),
    ])
    assert prior_attempts(store, SUBSTRATE) == []


def test_rejections_are_shown_before_failures():
    """A rejection is a human decision with a reason; a failure is often flaky."""
    store = FakeStore([
        FakeTask("f", "failed", SUBSTRATE, "2026-08-13T00:00:00"),
        FakeTask("r", "rejected", SUBSTRATE, "2026-08-07T00:00:00",
                 review_feedback="declined on principle"),
    ])
    prior = prior_attempts(store, SUBSTRATE)
    assert prior[0].status == "rejected", "the human decision must lead"


def test_the_warning_says_rejected_and_carries_the_reason():
    store = FakeStore([
        FakeTask("r", "rejected", SUBSTRATE, "2026-08-11T00:00:00",
                 review_feedback="Parallel store with no provenance model."),
    ])
    warning = dispatch_warning(prior_attempts(store, SUBSTRATE))
    assert "REJECTED" in warning
    assert "provenance" in warning


def test_no_prior_work_produces_no_noise():
    assert dispatch_warning([]) == ""
    assert prior_attempts(FakeStore([]), SUBSTRATE) == []


def test_a_broken_store_never_breaks_dispatch():
    """A guard that breaks dispatch is worse than no guard."""
    class Exploding:
        def list_tasks(self):
            raise RuntimeError("delegation db is locked")

    assert prior_attempts(Exploding(), SUBSTRATE) == []


def test_naming_the_same_file_counts_even_when_the_words_differ():
    store = FakeStore([
        FakeTask("t1", "failed", "Totally different phrasing about storage layers",
                 "2026-08-03T00:00:00", scope="soveryn/memory/substrate.py"),
    ])
    assert prior_attempts(store, SUBSTRATE), "shared target file is strong evidence"


def test_similarity_is_symmetric_and_bounded():
    a, b = SUBSTRATE, "Implement the Graph-Native Lattice Substrate"
    assert similarity(a, b) == pytest.approx(similarity(b, a))
    assert 0.0 <= similarity(a, b) <= 1.0
    assert similarity("", b) == 0.0
