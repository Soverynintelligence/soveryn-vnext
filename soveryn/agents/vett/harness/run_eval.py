"""Standalone CLI runner for the Vett harness eval.

Usage:
    python -m soveryn.agents.vett.harness.run_eval --task <name> --output <path.json>

Loads a SOVERYN eval task by name, runs it through the vendored harness
Agent backed by SoverynVettInferenceModel + LatticeToolHandlers, persists
the resulting Trajectory to JSON. Turn-budget enforcement and failure-mode
telemetry land in Tasks 9-10.

Phase 1: not wired into Vett's normal task surface. CLI-only.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any, List

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
    parser.add_argument("--lattice-db", default=None,
                        help="Override lattice SQLite path (default from env config).")
    parser.add_argument("--layer-filter", default="library",
                        help=(
                            "LatticeStore layer scope. 'library' (default) → "
                            "shared cross-author library layer (phase-1 eval "
                            "target). 'none' or empty → agent private+global "
                            "(library excluded). Any other value passes through."
                        ))
    return parser.parse_args(argv)


def load_task(name: str) -> EvalTask:
    """Resolve a task by name from the eval_tasks registry."""
    return get_task(name)


def _build_agent(args: argparse.Namespace) -> Any:
    """Construct the vendored harness ``Agent`` wired with SOVERYN shims.

    Imported lazily so the lattice / embed / OpenAI-client connections
    aren't required for unit tests that monkeypatch this function.

    Wiring shape (per vendor inspection at vendor/agent.py:872 and
    vendor/tools.py:812):

    - The vendored ``Agent.__init__`` takes ``toolset`` (positional first)
      and ``inference_model`` (positional second), plus an optional
      ``max_trajectory_length`` (default 32). It is NOT keyword-only — but
      we still pass by keyword here for readability.
    - The vendored ``Agent.__call__(initial_observation: Observation) ->
      Trajectory`` is the auto-drive entrypoint; there is no ``.run(task)``
      method. ``main()`` constructs the initial ``Observation`` from the
      eval task's query and calls the agent directly.
    - Tools must be subclasses of the vendored ``Tool`` ABC (Pydantic
      BaseModel) and registered with a ``ToolSet``. Task 6 deferred the
      Tool-subclass wrapping to here; we build minimal Tool subclasses
      that delegate to ``LatticeToolHandlers`` callables and return
      ``(text, None)``.

    Lattice + embed import paths (per Task 5 discovery
    docs/notes/2026-06-11-lattice-discovery.md):

    - ``soveryn.memory.lattice.LatticeStore`` (with ``db_path`` from
      ``load_env_config().recall_lattice_db``).
    - ``soveryn.memory.lattice.embed_text`` (sync HTTP to :8090
      ``model=embeddings``).

    ``layer_filter`` decision: default is ``"library"`` (CLI flag override
    available). Rationale: phase-1 eval targets cross-source linkage across
    the shared library layer; the default scope (``layer_filter=None``,
    Vett-private + global) excludes library and would yield empty results
    against the canonical eval corpus. Passing ``"none"`` or empty string
    on the CLI restores the agent-private scope. See Task 5 discovery
    "Agent-scoping decision is load-bearing" note.
    """
    from soveryn.agents.vett.harness.vendor.agent import Agent
    from soveryn.agents.vett.harness.vendor.tools import (
        Tool,
        ToolSchema,
        ToolSet,
    )
    from soveryn.agents.vett.harness.lattice_tools import LatticeToolHandlers
    from soveryn.agents.vett.harness.llm_client import SoverynVettInferenceModel
    from soveryn.memory.lattice import LatticeStore, embed_text
    from soveryn.config.loader import load_env_config

    # Resolve lattice DB path.
    if args.lattice_db:
        db_path = Path(args.lattice_db)
    else:
        env = load_env_config()
        db_path = env.recall_lattice_db

    lattice = LatticeStore(db_path)

    # Resolve layer filter ("none"/empty string → None for agent-private scope).
    raw_layer = (args.layer_filter or "").strip()
    layer_filter = None if raw_layer.lower() in ("", "none") else raw_layer

    handlers = LatticeToolHandlers(
        lattice=lattice,
        embed_fn=embed_text,
        agent_name="vett",
        layer_filter=layer_filter,
    )

    # Build Tool subclasses wrapping handler callables. Each returns
    # (text, None) — metadata is deferred (Task 10 may add telemetry).
    class _SearchCorpusTool(Tool):
        def __call__(self, params, overrides=None):
            query = params.get("query", "")
            return handlers.search_corpus(query=query), None

    class _ReadDocumentTool(Tool):
        def __call__(self, params, overrides=None):
            doc_id = params.get("doc_id") or params.get("id", "")
            return handlers.read_doc(doc_id=doc_id), None

    class _FanOutSearchTool(Tool):
        def __call__(self, params, overrides=None):
            queries = params.get("queries") or []
            return handlers.fan_out_search(queries=queries), None

    search_schema = ToolSchema(
        name="search_corpus",
        description=(
            "Search the SOVERYN lattice for documents relevant to the query. "
            "Returns up to a small set of (id, content) blocks."
        ),
        parameters={
            "query": {
                "type": "string",
                "description": "The search query.",
            }
        },
        required=["query"],
    )
    read_schema = ToolSchema(
        name="read_document",
        description="Read the full text of a lattice document by its ID.",
        parameters={
            "doc_id": {
                "type": "string",
                "description": "Document ID (lattice node UUID) to read.",
            }
        },
        required=["doc_id"],
    )
    fan_out_schema = ToolSchema(
        name="fan_out_search",
        description=(
            "Run multiple search queries and return concatenated results. "
            "Use when a single query is unlikely to surface all needed evidence."
        ),
        parameters={
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of search queries to run.",
            }
        },
        required=["queries"],
    )

    toolset = ToolSet(name="vett_lattice")
    toolset.add_tool(_SearchCorpusTool(tool_schema=search_schema))
    toolset.add_tool(_ReadDocumentTool(tool_schema=read_schema))
    toolset.add_tool(_FanOutSearchTool(tool_schema=fan_out_schema))

    inference_model = SoverynVettInferenceModel(
        router_url=args.router_url,
        model_name=args.model,
    )

    return Agent(
        toolset=toolset,
        inference_model=inference_model,
    )


def _build_initial_observation(task: EvalTask) -> Any:
    """Wrap an eval task's query into the harness ``Observation`` shape."""
    from soveryn.agents.vett.harness.vendor.trajectory import Observation
    return Observation(
        observations=[task.query],
        sources=["user"],
        tool_metadata=[None],
    )


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    task = load_task(args.task)
    print(f"loaded task: {task.name}", file=sys.stderr)

    agent = _build_agent(args)
    initial_observation = _build_initial_observation(task)
    trajectory = agent(initial_observation)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(trajectory, "model_dump"):
        trajectory_dict = trajectory.model_dump()
    else:
        trajectory_dict = dict(trajectory)
    out_path.write_text(json.dumps(trajectory_dict, indent=2, default=str))
    print(f"wrote trajectory: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
