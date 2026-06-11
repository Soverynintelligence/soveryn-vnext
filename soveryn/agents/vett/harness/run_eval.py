"""Standalone CLI runner for the Vett harness eval.

Usage:
    python -m soveryn.agents.vett.harness.run_eval --task <name> --output <path.json>

Loads a SOVERYN eval task by name, runs it through the vendored harness
Agent backed by SoverynVettInferenceModel + LatticeToolHandlers, enforces
a turn budget, persists the resulting Trajectory to JSON, and emits
failure-mode telemetry on stderr.

Phase 1: not wired into Vett's normal task surface. CLI-only.
"""
from __future__ import annotations
import argparse
import sys
from dataclasses import dataclass
from typing import List

from soveryn.agents.vett.harness.eval_tasks import get_task, EvalTask


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_eval",
        description="Run a SOVERYN eval task through the Vett harness port.",
    )
    parser.add_argument("--task", required=True, help="Name of eval task to load.")
    parser.add_argument("--output", required=True, help="Path to write Trajectory JSON.")
    parser.add_argument("--max-turns", type=int, default=20,
                        help="Max harness turns before forced stop (default 20).")
    parser.add_argument("--router-url", default="http://127.0.0.1:8090",
                        help="llama-server router URL (default :8090).")
    parser.add_argument("--model", default="vett-scotty",
                        help="Router model alias (default vett-scotty).")
    return parser.parse_args(argv)


def load_task(name: str) -> EvalTask:
    """Resolve a task by name from the eval_tasks registry."""
    return get_task(name)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    task = load_task(args.task)
    print(f"loaded task: {task.name}", file=sys.stderr)
    # Task 8 wires the actual harness Agent in; for now, exit clean.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
