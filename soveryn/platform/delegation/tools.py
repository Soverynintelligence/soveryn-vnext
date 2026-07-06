"""Delegation tool factories for SOVERYN vNext.

Provides Aetheria's `dispatch_task` tool — her rail for handing a scoped
implementation task to Scotty.

The tool enforces three hard constraints at invocation time:
  1. All three fields (objective, scope, acceptance) must be non-empty strings.
  2. The acceptance criterion must be a runnable test/check command, identified
     by a required prefix: ``pytest``, ``python -m``, or ``./``.

These are gates, not suggestions.  An acceptance criterion that is ambiguous
prose ("looks good", "echo done") will not pass.  If Aetheria cannot express
a concrete test command, she should not dispatch yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.delegation.store import DelegationStore
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec

# Prefixes that identify a runnable test / check command.
_ACCEPTANCE_PREFIXES = ("pytest", "python -m", "./")


# ---------------------------------------------------------------------------
# build_dispatch_task_tool
# ---------------------------------------------------------------------------

def build_dispatch_task_tool(
    *,
    store: DelegationStore,
    owner_agent: str = "aetheria",
) -> ToolSpec:
    """Tool that dispatches a scoped implementation task to Scotty.

    Aetheria uses this to hand off a bounded, well-specified piece of work
    with a concrete acceptance criterion.  The task runs in an isolated
    worktree, gets tested, and comes back as a proposal for Jon to review.
    Nothing lands until approved.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        objective = args.get("objective", "")
        if not isinstance(objective, str) or not objective.strip():
            raise ToolArgError("objective must be a non-empty string")

        scope = args.get("scope", "")
        if not isinstance(scope, str) or not scope.strip():
            raise ToolArgError("scope must be a non-empty string")

        acceptance = args.get("acceptance", "")
        if not isinstance(acceptance, str) or not acceptance.strip():
            raise ToolArgError("acceptance must be a non-empty string")

        # Gate: acceptance must be a runnable test/check command.
        if not any(acceptance.strip().startswith(p) for p in _ACCEPTANCE_PREFIXES):
            raise ToolArgError(
                "acceptance must be a test/check command starting with "
                "'pytest', 'python -m', or './' — "
                f"got: {acceptance!r}"
            )

        task_id = store.create_task(
            dispatched_by=owner_agent,
            objective=objective.strip(),
            scope=scope.strip(),
            acceptance=acceptance.strip(),
        )
        return {"task_id": task_id, "status": "dispatched"}

    return ToolSpec(
        name="dispatch_task",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "objective": {
                    "type": "string",
                    "description": (
                        "Clear, specific description of what Scotty must implement. "
                        "Write it as a bounded deliverable, not an open-ended goal. "
                        "Example: 'Add a retry loop with exponential backoff to the "
                        "fetch_document function in soveryn/lattice/fetcher.py'."
                    ),
                },
                "scope": {
                    "type": "string",
                    "description": (
                        "Hard boundary on what files or modules Scotty may touch. "
                        "Be explicit — list specific files or directories. "
                        "Example: 'soveryn/lattice/fetcher.py only; no other files'. "
                        "Scotty operates within this scope; anything outside it is off-limits."
                    ),
                },
                "acceptance": {
                    "type": "string",
                    "description": (
                        "A concrete, runnable test or check command that must pass "
                        "for the task to be considered done. Must start with 'pytest', "
                        "'python -m', or './'. Prose like 'looks good' is not accepted. "
                        "Example: 'pytest tests/test_fetcher.py -q --tb=short'."
                    ),
                },
            },
            "required": ["objective", "scope", "acceptance"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Dispatch a scoped implementation task to Scotty. It runs in an isolated "
            "worktree, is tested, and comes back as a proposal for Jon to review — "
            "nothing goes live until approved. Returns a task_id; check task_status "
            "for progress. This ACTUALLY runs; do not say a task is done until its "
            "status is 'landed'. Supply a concrete test command (pytest / python -m / "
            "./script) as the acceptance criterion — vague prose is rejected."
        ),
    )


# ---------------------------------------------------------------------------
# register_delegation_tools
# ---------------------------------------------------------------------------

def register_delegation_tools(
    registry: ToolRegistry,
    *,
    store: DelegationStore,
    owner_agent: str = "aetheria",
) -> None:
    """Register all delegation tools for one agent.

    Call once for the agent that owns the delegation surface (Aetheria).
    """
    registry.register(build_dispatch_task_tool(store=store, owner_agent=owner_agent))
