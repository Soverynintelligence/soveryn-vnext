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


def test_build_agent_forwards_max_turns_to_vendored_agent(monkeypatch):
    """Real _build_agent must pass max_trajectory_length=args.max_turns
    to the vendored Agent's constructor (the seam at vendor/agent.py:905
    that gates the runtime turn-budget check at vendor/agent.py:990).

    Spy approach: monkeypatch the vendored Agent.__init__ to capture
    kwargs, then abort before the real init runs (so we don't need a
    live lattice / embed / router). Stubs LatticeStore + embed_text so
    _build_agent's lazy imports don't reach live services.
    """
    from soveryn.agents.vett.harness.vendor.agent import Agent as VendoredAgent

    captured = {}

    def _spy_init(self, *args, **kwargs):
        # Capture both positional and keyword forms so the test is robust
        # to either passing style in _build_agent.
        captured["args"] = args
        captured["kwargs"] = kwargs
        raise RuntimeError("captured init, aborting real construction")

    monkeypatch.setattr(VendoredAgent, "__init__", _spy_init)

    import soveryn.memory.lattice as _lat_mod
    monkeypatch.setattr(_lat_mod, "LatticeStore", lambda *a, **kw: object())
    monkeypatch.setattr(_lat_mod, "embed_text", lambda text: tuple([0.0] * 768))

    args = run_eval.parse_args([
        "--task", "smoke",
        "--output", "/tmp/x.json",
        "--max-turns", "7",
    ])
    with pytest.raises(RuntimeError, match="aborting real construction"):
        run_eval._build_agent(args)

    # Accept either kwarg form (preferred) or positional 3rd arg.
    forwarded = captured["kwargs"].get("max_trajectory_length")
    if forwarded is None and len(captured["args"]) >= 3:
        forwarded = captured["args"][2]
    assert forwarded == 7, (
        f"_build_agent did not forward --max-turns to vendored Agent. "
        f"captured args={captured['args']!r} kwargs={captured['kwargs']!r}"
    )
