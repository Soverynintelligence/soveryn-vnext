"""Eval task registry — phase 1 SOVERYN tasks."""
from __future__ import annotations
import pytest

from soveryn.agents.vett.harness.eval_tasks import get_task


def test_cross_source_link_task_is_registered():
    task = get_task("cross_source_link")
    assert task.name == "cross_source_link"
    assert "topic" in task.query.lower() or "claim" in task.query.lower()


def test_cross_source_link_task_has_expected_evidence_ids():
    """The task carries the canonical answer-set so the comparison run can score it."""
    task = get_task("cross_source_link")
    assert len(task.expected_evidence_ids) >= 3
