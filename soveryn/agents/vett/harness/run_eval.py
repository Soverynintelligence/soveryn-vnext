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


DOMINANT_TOOL_FRACTION_THRESHOLD = 0.8
# tool_diversity_collapse only fires once enough calls have been made that
# "dominance" is a meaningful signal. 1/1 and 2/2 trivially clear the 80%
# bar but don't represent a stuck loop. Three is the smallest count where
# the ratio actually distinguishes "varied" from "stuck on one tool".
TOOL_DIVERSITY_MIN_CALLS = 3


def _tool_name(tool: Any) -> str:
    """Resolve a Tool object's name across two paths.

    The vendored ``Tool`` carries its name at ``tool_schema.name``
    (vendor/tools.py:266+). Test fakes and any future flat-shape adapters
    may expose ``.name`` directly. Prefer the vendor path; fall back.
    Returns ``"unknown"`` only when neither is present.
    """
    schema = getattr(tool, "tool_schema", None)
    if schema is not None:
        schema_name = getattr(schema, "name", None)
        if schema_name:
            return schema_name
    return getattr(tool, "name", "unknown")


def emit_telemetry(
    trajectory: Any,
    *,
    max_turns: int,
    reached_stop: bool,
    evidence_promoted: int,
) -> dict:
    """Aggregate per-trajectory failure-mode telemetry.

    Returns the dict for testability. The CLI's ``main()`` also prints a
    one-line stderr summary derived from the same dict.

    Failure-mode fields:
        - ``turn_cap_hit``: ran out of turn budget without natural stop
        - ``zero_promotion``: never promoted any evidence to the curated set
        - ``tool_diversity_collapse``: one tool dominated >80% of calls
          (e.g., searched forever, never verified)
        - ``tool_error_count``: count of actions where the tool errored
          (driven off ``entry.errored``, which the vendored ``Action``
          does NOT currently expose — defaults to 0 for real trajectories
          until Task 13 wires a real error signal)
    """
    tool_call_counts: dict[str, int] = {}
    tool_error_count = 0
    for entry in getattr(trajectory, "actions_and_observations", []) or []:
        for tool in getattr(entry, "tools", []) or []:
            name = _tool_name(tool)
            tool_call_counts[name] = tool_call_counts.get(name, 0) + 1
        if getattr(entry, "errored", False):
            tool_error_count += 1

    num_turns = getattr(trajectory, "num_turns", -1)
    total_calls = sum(tool_call_counts.values())
    # Gate on >=3 calls so a single tool call (1/1=100%) or a pair
    # (2/2=100%) doesn't trip the dominance check on trivial runs.
    tool_diversity_collapse = (
        total_calls >= TOOL_DIVERSITY_MIN_CALLS
        and max(tool_call_counts.values()) / total_calls > DOMINANT_TOOL_FRACTION_THRESHOLD
    )

    return {
        "num_turns": num_turns,
        "tool_calls": tool_call_counts,
        "reached_stop": reached_stop,
        "evidence_promoted": evidence_promoted,
        # Failure-mode diagnostics
        "turn_cap_hit": num_turns >= max_turns,
        "zero_promotion": evidence_promoted == 0,
        "tool_diversity_collapse": tool_diversity_collapse,
        "tool_error_count": tool_error_count,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_eval",
        description="Run a SOVERYN eval task through the Vett harness port.",
    )
    parser.add_argument("--task", required=True, help="Name of eval task to load.")
    parser.add_argument("--output", required=True, help="Path to write Trajectory JSON.")
    parser.add_argument("--max-turns", type=int, default=20,
                        help=("Max trajectory length forwarded to the vendored "
                              "Agent (default 20; vendored default 32). When "
                              "exceeded, the harness raises RuntimeError mid-run."))
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
        max_trajectory_length=args.max_turns,
    )


def _build_initial_observation(task: EvalTask) -> Any:
    """Wrap an eval task's query into the harness ``Observation`` shape."""
    from soveryn.agents.vett.harness.vendor.trajectory import Observation
    return Observation(
        observations=[task.query],
        sources=["user"],
        tool_metadata=[None],
    )


def _trajectory_reached_natural_stop(trajectory: Any) -> bool:
    """True if the trajectory's last entry is an Action consisting only of
    user_text tool calls (the vendored Agent's natural-stop signal).

    Mirrors vendor/agent.py:960-968 ``_finished_with_user_text``. Reads
    the serialized shape (tool_schema.name) so it works on both live
    Trajectory objects and replayed dicts/Pydantic instances.
    """
    entries = getattr(trajectory, "actions_and_observations", None) or []
    if not entries:
        return False
    last = entries[-1]
    # Observations don't have .tools; only Actions do.
    tools = getattr(last, "tools", None)
    if not tools:
        return False
    # All tools must be user_text for "natural stop".
    return all(_tool_name(t) == "user_text" for t in tools)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    task = load_task(args.task)
    print(f"loaded task: {task.name}", file=sys.stderr)

    agent = _build_agent(args)
    initial_observation = _build_initial_observation(task)
    trajectory = agent(initial_observation)

    # Failure-mode telemetry.
    #
    # reached_stop: mirror the vendored Agent's natural-stop check
    # (vendor/agent.py:960-968) — the agent stops auto-driving when the
    # last entry is an Action whose tools are ALL UserTextTool. We read
    # the same shape from the serialized trajectory: last entry has at
    # least one tool, and every tool's name is "user_text".
    #
    # evidence_promoted: SOVERYN-side convention — the vendored
    # Trajectory has no curated-evidence slot (vendor/trajectory.py:228).
    # Phase 1 doesn't add one; the field defaults to 0 here and the
    # writeup scores promotion qualitatively from the trajectory.
    reached_stop = _trajectory_reached_natural_stop(trajectory)
    evidence_promoted = len(getattr(trajectory, "promoted_evidence_ids", []) or [])
    summary = emit_telemetry(
        trajectory,
        max_turns=args.max_turns,
        reached_stop=reached_stop,
        evidence_promoted=evidence_promoted,
    )
    print(
        f"[telemetry] num_turns={summary['num_turns']} "
        f"tool_calls={summary['tool_calls']} "
        f"reached_stop={summary['reached_stop']} "
        f"evidence_promoted={summary['evidence_promoted']} "
        f"turn_cap_hit={summary['turn_cap_hit']} "
        f"zero_promotion={summary['zero_promotion']} "
        f"tool_diversity_collapse={summary['tool_diversity_collapse']} "
        f"tool_error_count={summary['tool_error_count']}",
        file=sys.stderr,
    )

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
