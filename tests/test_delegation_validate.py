"""Dispatch-time validation: reject unrunnable acceptance, ground the paths.

The regression these lock down is concrete. Five of the eleven acceptance
commands ever dispatched took the form `python -m tests.test_x` — a module run
directly, which clears a `python -m` prefix check and then does not run a suite.
Four of the ten failures were sealed before Scotty was even started.
"""
from __future__ import annotations

import pytest

from soveryn.platform.delegation.validate import (
    acceptance_problem,
    ground_truth_block,
    path_facts,
    referenced_paths,
)


class TestAcceptanceGate:
    """acceptance_problem() rejects what cannot pass, and only that."""

    @pytest.mark.parametrize("cmd", [
        "pytest tests/test_x.py -q",
        "pytest tests/test_x.py -k \"not slow\"",
        "python -m pytest tests/test_x.py -q --tb=short",
        "python3 -m pytest tests/",
        "python -m unittest tests.test_x",
        "python -m mypy soveryn/",
        "python -m ruff check soveryn/",
    ])
    def test_real_runners_are_accepted(self, cmd):
        assert acceptance_problem(cmd) is None, cmd

    @pytest.mark.parametrize("cmd", [
        # The exact five that were dispatched for real and could never pass.
        "python -m tests.test_compliance_state_machine",
        "python -m tests.test_active_context --run-smoke",
        "python -m tests.test_active_context --run-fast",
        "python -m tests.test_pond_logic",
        "python -m tests.test_cross_rail_context --verbose",
    ])
    def test_the_historical_failures_are_rejected(self, cmd):
        problem = acceptance_problem(cmd)
        assert problem is not None, f"{cmd!r} should have been rejected"
        # The message must tell the agent what to write instead, not just "no".
        assert "pytest" in problem

    @pytest.mark.parametrize("cmd", [
        "",
        "   ",
        "looks good",
        "echo done",
        "./run_tests.sh",
        "python tests/test_x.py",          # script, not a check
        "python -m",                        # truncated
        'pytest "unbalanced',               # unparseable
    ])
    def test_non_commands_are_rejected(self, cmd):
        assert acceptance_problem(cmd) is not None, cmd

    def test_rejection_names_the_offending_module(self):
        problem = acceptance_problem("python -m tests.test_cross_rail_context --verbose")
        assert "tests.test_cross_rail_context" in problem


class TestReferencedPaths:
    def test_finds_paths_in_prose(self):
        found = referenced_paths(
            "Create soveryn/platform/delegation/humanize.py with format_age().",
            "soveryn/context/ only",
            "python -m pytest tests/test_humanize.py -q",
        )
        assert "soveryn/platform/delegation/humanize.py" in found
        assert "soveryn/context/" in found
        assert "tests/test_humanize.py" in found

    def test_dotted_module_names_are_not_paths(self):
        assert referenced_paths("import soveryn.platform.delegation.store") == []

    def test_urls_are_ignored(self):
        assert referenced_paths("see https://example.com/docs/x") == []

    def test_order_is_stable_and_deduplicated(self):
        found = referenced_paths("a/one.py then b/two.py then a/one.py")
        assert found == ["a/one.py", "b/two.py"]


class TestPathFacts:
    def test_splits_existing_from_missing(self, tmp_path):
        (tmp_path / "there.py").write_text("x")
        existing, missing = path_facts(["there.py", "gone.py"], tmp_path)
        assert existing == ["there.py"]
        assert missing == ["gone.py"]


class TestGroundTruthBlock:
    def test_empty_when_no_paths_named(self, tmp_path):
        assert ground_truth_block("do a thing", "carefully", "pytest", tmp_path) == ""

    def test_marks_missing_paths_and_says_they_may_be_the_task(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_here.py").write_text("x")
        block = ground_truth_block(
            "create soveryn/context/manager.py",
            "soveryn/context/ only",
            "python -m pytest tests/test_here.py -q",
            tmp_path,
        )
        assert "EXISTS       tests/test_here.py" in block
        assert "DOES NOT EXIST  soveryn/context/manager.py" in block
        assert "not necessarily an error" in block

    def test_no_advisory_when_nothing_is_missing(self, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_here.py").write_text("x")
        block = ground_truth_block("x", "y", "pytest tests/test_here.py", tmp_path)
        assert "DOES NOT EXIST" not in block
        assert "not necessarily an error" not in block
