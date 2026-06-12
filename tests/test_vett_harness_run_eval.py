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


def test_main_emits_telemetry_to_stderr(monkeypatch, capsys):
    """Telemetry block is written to stderr after the run."""

    class _FakeTrajectory:
        actions_and_observations = []
        @property
        def num_turns(self): return 3
        def model_dump(self): return {"actions_and_observations": [], "id": "fake"}

    class _FakeAgent:
        def __init__(self, *a, **kw): pass
        def __call__(self, initial_observation): return _FakeTrajectory()

    monkeypatch.setattr(
        "soveryn.agents.vett.harness.run_eval._build_agent",
        lambda args: _FakeAgent(),
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "trajectory.json"
        rc = run_eval.main(["--task", "smoke", "--output", str(out_path)])
        captured = capsys.readouterr()
        assert "[telemetry]" in captured.err
        assert "num_turns=3" in captured.err


def test_telemetry_counts_tool_calls_by_name():
    """Direct call: telemetry helper aggregates tool-call counts from a trajectory."""
    from soveryn.agents.vett.harness.run_eval import emit_telemetry

    class _FakeAction:
        def __init__(self, tool_name, errored=False):
            self.tools = [type("T", (), {"name": tool_name})()]
            self.params = [{}]
            self.errored = errored

    class _FakeTraj:
        num_turns = 4
        actions_and_observations = [
            _FakeAction("search_corpus"),
            _FakeAction("search_corpus"),
            _FakeAction("read_doc"),
            _FakeAction("verify", errored=True),
        ]

    summary = emit_telemetry(
        _FakeTraj(),
        max_turns=20,
        reached_stop=True,
        evidence_promoted=2,
    )
    assert summary["num_turns"] == 4
    assert summary["tool_calls"]["search_corpus"] == 2
    assert summary["tool_calls"]["read_doc"] == 1
    assert summary["reached_stop"] is True
    assert summary["evidence_promoted"] == 2
    # Failure-mode diagnostics
    assert summary["turn_cap_hit"] is False        # 4 < 20
    assert summary["zero_promotion"] is False      # promoted_evidence == 2
    assert summary["tool_diversity_collapse"] is False  # 3 distinct tools
    assert summary["tool_error_count"] == 1        # one errored action


def test_telemetry_flags_turn_cap_hit():
    """turn_cap_hit fires when num_turns hits max_turns."""
    from soveryn.agents.vett.harness.run_eval import emit_telemetry

    class _FakeTraj:
        num_turns = 20
        actions_and_observations = []

    summary = emit_telemetry(_FakeTraj(), max_turns=20, reached_stop=False, evidence_promoted=0)
    assert summary["turn_cap_hit"] is True
    assert summary["zero_promotion"] is True


def test_telemetry_flags_tool_diversity_collapse():
    """tool_diversity_collapse fires when one tool dominates >80% of calls."""
    from soveryn.agents.vett.harness.run_eval import emit_telemetry

    class _FakeAction:
        def __init__(self, tool_name):
            self.tools = [type("T", (), {"name": tool_name})()]
            self.params = [{}]
            self.errored = False

    class _FakeTraj:
        num_turns = 10
        # 9 search_corpus, 1 verify — search dominates 90%
        actions_and_observations = [_FakeAction("search_corpus")] * 9 + [_FakeAction("verify")]

    summary = emit_telemetry(_FakeTraj(), max_turns=20, reached_stop=True, evidence_promoted=1)
    assert summary["tool_diversity_collapse"] is True


def test_telemetry_does_not_flag_diversity_on_trivial_trajectories():
    """tool_diversity_collapse must NOT fire on 1/1 or 2/2 — a single call
    or pair trivially clears 80% but isn't a stuck-loop signal."""
    from soveryn.agents.vett.harness.run_eval import emit_telemetry

    class _FakeAction:
        def __init__(self, tool_name):
            self.tools = [type("T", (), {"name": tool_name})()]
            self.params = [{}]
            self.errored = False

    class _Single:
        num_turns = 1
        actions_and_observations = [_FakeAction("search_corpus")]

    class _Pair:
        num_turns = 2
        actions_and_observations = [_FakeAction("search_corpus"), _FakeAction("search_corpus")]

    assert emit_telemetry(_Single(), max_turns=20, reached_stop=True,
                          evidence_promoted=0)["tool_diversity_collapse"] is False
    assert emit_telemetry(_Pair(), max_turns=20, reached_stop=True,
                          evidence_promoted=0)["tool_diversity_collapse"] is False


def test_reached_stop_detected_from_terminal_user_text_action():
    """_trajectory_reached_natural_stop mirrors the vendored agent's
    natural-stop check: last action's tools are all user_text."""
    from soveryn.agents.vett.harness.run_eval import (
        _trajectory_reached_natural_stop,
    )

    def _action(*tool_names):
        return type("A", (), {
            "tools": [
                type("T", (), {
                    "tool_schema": type("S", (), {"name": n})(),
                })()
                for n in tool_names
            ],
            "params": [{}] * len(tool_names),
            "errored": False,
        })()

    # Last is all user_text → natural stop.
    traj_stop = type("Tr", (), {
        "actions_and_observations": [
            _action("search_corpus"),
            _action("user_text"),
        ],
    })()
    assert _trajectory_reached_natural_stop(traj_stop) is True

    # Last has a non-text tool → did NOT naturally stop.
    traj_no_stop = type("Tr", (), {
        "actions_and_observations": [
            _action("search_corpus"),
            _action("read_document"),
        ],
    })()
    assert _trajectory_reached_natural_stop(traj_no_stop) is False

    # Empty trajectory → not stopped.
    traj_empty = type("Tr", (), {"actions_and_observations": []})()
    assert _trajectory_reached_natural_stop(traj_empty) is False

    # Last is an observation (no .tools) → not stopped.
    traj_obs = type("Tr", (), {
        "actions_and_observations": [
            _action("search_corpus"),
            type("O", (), {})(),
        ],
    })()
    assert _trajectory_reached_natural_stop(traj_obs) is False
