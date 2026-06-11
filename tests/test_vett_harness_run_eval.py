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
