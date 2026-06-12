"""SOVERYN eval-task registry.

Tasks are simple dataclasses with a name and a query. Task 11 (the
cross_source_link eval task) populates the registry with a real
SOVERYN-representative task. For now, a 'smoke' task is registered so
the CLI skeleton has something to load.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class EvalTask:
    name: str
    query: str
    expected_evidence_ids: tuple = ()  # for scoring; populated by Task 11 (cross_source_link)


_REGISTRY: Dict[str, EvalTask] = {
    "smoke": EvalTask(
        name="smoke",
        query="reply with: SMOKE_OK",
    ),
}


def get_task(name: str) -> EvalTask:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown eval task: {name!r}. Registered: {list(_REGISTRY)}")
    return _REGISTRY[name]


def register_task(task: EvalTask) -> None:
    _REGISTRY[task.name] = task


# Trigger registration of phase-1 tasks. Imported at the bottom so the
# registry primitives above are fully defined before the task modules
# call ``register_task`` at import time.
from soveryn.agents.vett.harness.eval_tasks import cross_source_link  # noqa: F401, E402
