"""Delegation tool factories for SOVERYN vNext.

Provides Aetheria's `dispatch_task` tool — her rail for handing a scoped
implementation task to Scotty.

The tool enforces three hard constraints at invocation time:
  1. All three fields (objective, scope, acceptance) must be non-empty strings.
  2. The acceptance criterion must be a runnable test/check command, identified
     by a required prefix: ``pytest`` or ``python -m``. A bare ``./script``
     prefix is deliberately NOT allowed — acceptance runs as a real subprocess,
     and letting it execute any file in the worktree (which Scotty writes) is a
     broader code-execution surface than a test invocation.

These are gates, not suggestions.  An acceptance criterion that is ambiguous
prose ("looks good", "echo done") will not pass.  If Aetheria cannot express
a concrete test command, she should not dispatch yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.delegation.store import DelegationStore
from soveryn.platform.delegation.validate import acceptance_problem
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec

# The allowlist of real check runners now lives in validate.CHECK_RUNNERS.
# "./script" remains excluded: acceptance runs as a real subprocess and a bare
# script prefix would let it execute ANY file in the worktree (which Scotty
# writes). Constrain the entrypoint to a known runner.


# Statuses in which a task is still live — a second dispatch of the same
# objective would duplicate work rather than retry it. A `failed` or `rejected`
# task is deliberately NOT here: re-dispatching after a failure is legitimate.
_LIVE_STATUSES: frozenset[str] = frozenset({"dispatched", "executing", "in_review"})


def _find_open_duplicate(store: DelegationStore, objective: str):
    """Return a live task with the same objective, or None.

    Compared on normalised whitespace and case so that a re-worded-but-identical
    objective still matches; the five dispatches on 2026-07-28 differed only in
    incidental spacing.
    """
    def norm(text: str) -> str:
        return " ".join((text or "").split()).casefold()

    target = norm(objective)
    try:
        for task in store.list_tasks():
            if task.status in _LIVE_STATUSES and norm(task.objective) == target:
                return task
    except Exception:
        return None      # a guard that breaks dispatch is worse than no guard
    return None


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

        # Gate: acceptance must be a command that actually RUNS a check.
        # The old gate accepted any 'python -m' prefix, which let through five
        # real dispatches of the form 'python -m tests.test_x' — a module run
        # directly, which never executes a suite. See validate.acceptance_problem.
        problem = acceptance_problem(acceptance)
        if problem is not None:
            raise ToolArgError(problem)

        # ── Duplicate guard ──────────────────────────────────────────────
        # 2026-07-28, 20:50→22:50: the same Cross-Rail task was dispatched five
        # times, once per heartbeat pulse, each run waking Scotty for 10–20
        # minutes of GPU. The work had already been merged that morning and one
        # dispatch was already sitting in_review. Nothing she could read said
        # so — the board still showed Ready, and a heartbeat pulse carries no
        # memory of what a previous pulse dispatched.
        #
        # She was told in conversation that it was done. That did not survive
        # into the next pulse, because a fact stated on one rail has no path
        # into an autonomous session. So this is enforced in code, where it
        # cannot be forgotten, rather than in prose she may not be carrying.
        #
        # Returns the EXISTING task rather than raising: the useful answer to
        # "dispatch this" when it is already running is "you already did, here
        # it is, here is its status" — which is also the read path that was
        # missing.
        existing = _find_open_duplicate(store, objective.strip())
        if existing is not None:
            return {
                "task_id": existing.id,
                "status": existing.status,
                "duplicate": True,
                "message": (
                    f"Already dispatched. Task {existing.id} was created at "
                    f"{existing.created_at} and is currently '{existing.status}'. "
                    "Not dispatching again. Check its status or wait for review "
                    "rather than re-sending."
                ),
            }

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
                        "for the task to be considered done. Must start with 'pytest' "
                        "or 'python -m'. Prose like 'looks good' is not accepted. "
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
            "status is 'landed'. Supply a concrete test command (pytest / python -m) "
            "as the acceptance criterion — vague prose is rejected."
        ),
    )


# ---------------------------------------------------------------------------
# build_task_status_tool
# ---------------------------------------------------------------------------

_OPEN_STATUSES: frozenset[str] = frozenset({"dispatched", "executing", "in_review"})


def build_task_status_tool(
    *,
    store: DelegationStore,
    owner_agent: str = "aetheria",
) -> ToolSpec:
    """Tool that lets Aetheria check the real status of a dispatched task.

    Call with a task_id to get one task's full status info, or with no args
    to list all open (non-terminal) tasks.  This is the grounding tool that
    prevents Aetheria from reporting a task as done before it has landed.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        task_id = args.get("task_id")

        if task_id is not None:
            # Single-task lookup
            task = store.get_task(task_id)
            if task is None:
                return {"error": "not_found", "task_id": task_id}
            return {
                "id": task.id,
                "status": task.status,
                "objective": task.objective,
                "summary": task.summary,
                "review_feedback": task.review_feedback,
            }

        # No task_id → list open (non-terminal) tasks, newest-first
        all_tasks = store.list_tasks()
        return [
            {"id": t.id, "status": t.status, "objective": t.objective}
            for t in all_tasks
            if t.status in _OPEN_STATUSES
        ]

    return ToolSpec(
        name="task_status",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": (
                        "The task id returned by dispatch_task. "
                        "Omit to list all your open tasks instead."
                    ),
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Check the real status of a task you dispatched "
            "(dispatched → executing → in_review → landed/rejected/failed). "
            "Call with a task_id for one task, or with no args to list your open tasks. "
            "Use this to report truthfully — a task is only done when its status is 'landed'."
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
    registry.register(build_task_status_tool(store=store, owner_agent=owner_agent))
