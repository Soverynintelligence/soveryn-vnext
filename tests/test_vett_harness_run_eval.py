"""run_eval CLI runner — argparse + task loading + JSON output."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

import pytest

from soveryn.agents.vett.harness import run_eval


def test_parse_args_minimal():
    """CLI accepts --task and --output args."""
    args = run_eval.parse_args(["--task", "smoke", "--output", "/tmp/out.json"])
    assert args.task == "smoke"
    assert args.output == "/tmp/out.json"


def test_parse_args_has_turn_budget_default():
    """Default turn budget is 20 (per spec)."""
    args = run_eval.parse_args(["--task", "smoke", "--output", "/tmp/out.json"])
    assert args.max_turns == 20


def test_parse_args_accepts_turn_budget_override():
    """--max-turns flag overrides the default."""
    args = run_eval.parse_args(["--task", "smoke", "--output", "/tmp/out.json", "--max-turns", "5"])
    assert args.max_turns == 5


def test_load_task_returns_task_object_for_known_task():
    """A built-in task is loadable by name."""
    task = run_eval.load_task("smoke")
    assert task.name == "smoke"
    assert task.query


def test_main_persists_trajectory_json_with_fake_harness(monkeypatch):
    """main() runs the harness against a task and writes a JSON file."""
    fake_trajectory_dict = {"actions_and_observations": [], "id": "fake-uuid"}

    class _FakeTrajectory:
        def model_dump(self):
            return fake_trajectory_dict

    class _FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, initial_observation):
            return _FakeTrajectory()

    monkeypatch.setattr(
        "soveryn.agents.vett.harness.run_eval._build_agent",
        lambda args: _FakeAgent(),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "trajectory.json"
        rc = run_eval.main(["--task", "smoke", "--output", str(out_path)])
        assert rc == 0
        assert out_path.exists()
        loaded = json.loads(out_path.read_text())
        assert loaded["id"] == "fake-uuid"
