"""One hand must know what the other is doing — enforced, not remembered.

Jon, 2026-07-28: "my belief is one hand has to know what the other is doing or
it breaks. tonight was the perfect example."

Six times in two days the same defect appeared, each time in different clothes,
each time because two subsystems built weeks apart were never joined:

    the audit tool could not see delegations   → she confessed to a fabrication
                                                  she had not committed
    no surface listed staged X posts           → five expired unseen
    heartbeat notes were sealed in-session     → 733 written, 0 surfaced
    nothing said a document already existed    → it was written seven times
    nothing said a task was already in flight  → it was dispatched five times,
                                                  10-20 min of GPU each
    the delegated executor was wired to none   → he could not know any of it

Every one was fixed by hand, and every fix relied on somebody REMEMBERING to
wire the new thing up. Today also proved twice that a thing you have to remember
is not a control: a prose caveat in the audit tool was read and overridden, and
an acceptance gate that could not fail passed anyway.

So this file does not test behaviour. It tests that the wiring EXISTS, at every
site where an agent is constructed, and fails if a new one appears unwired.
If you are here because this test broke: you added a place where an agent is
built. Give it the shared context, or add it below with a stated reason.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Construction sites that legitimately do NOT take shared context, with reasons.
# Adding to this list is a decision; leaving a site out of it is a bug.
EXEMPT: dict[str, str] = {}


def _agentloop_call_sites() -> list[tuple[Path, int, ast.Call]]:
    """Every AgentLoop(...) construction in the package, found by parsing."""
    sites: list[tuple[Path, int, ast.Call]] = []
    for path in (REPO / "soveryn").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name == "AgentLoop":
                sites.append((path, node.lineno, node))
    return sites


class TestEveryAgentSeesTheTeam:

    def test_at_least_two_construction_sites_exist(self):
        """Guard the guard: if the scan finds nothing, it proves nothing."""
        sites = _agentloop_call_sites()
        assert len(sites) >= 2, (
            f"expected to find the app and delegation construction sites, "
            f"found {len(sites)} — the scanner is broken, not the code"
        )

    def test_every_agentloop_is_given_shared_context(self):
        missing = []
        for path, lineno, node in _agentloop_call_sites():
            rel = str(path.relative_to(REPO))
            if rel in EXEMPT:
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            # `**kwargs` forwarding (arg is None) counts — startup.py builds its
            # dict above the call and we assert its contents separately below.
            forwards = any(kw.arg is None for kw in node.keywords)
            if "active_context" not in kwargs and not forwards:
                missing.append(f"{rel}:{lineno}")

        assert not missing, (
            "These build an agent without the shared cross-rail context:\n  "
            + "\n  ".join(missing)
            + "\n\nAn agent that cannot see what the rest of the fleet has done "
              "will repeat work that is already finished. That happened five "
              "times in two hours on 2026-07-28. Wire it, or add the site to "
              "EXEMPT with a reason."
        )

    def test_startup_gives_every_active_agent_a_context_service(self):
        """The kwargs-dict path in startup.py, asserted on the source."""
        src = (REPO / "soveryn/app/startup.py").read_text(encoding="utf-8")
        assert "active_context_services" in src
        assert 'kwargs["active_context"]' in src, (
            "startup.py builds AgentLoop from a kwargs dict; that dict must "
            "carry active_context or the agents launch blind"
        )

    def test_the_delegation_chain_threads_context_end_to_end(self):
        """run_forever → _drain → execute_task → scotty_run → AgentLoop.

        A break anywhere in that chain silently returns the executor to the
        state it was in on 2026-07-28: knowing nothing.
        """
        from soveryn.platform.delegation.engine import execute_task
        from soveryn.platform.delegation.scotty_runner import scotty_run
        from soveryn.platform.delegation.worker import run_forever

        for fn in (run_forever, execute_task, scotty_run):
            params = inspect.signature(fn).parameters
            assert "active_context" in params, (
                f"{fn.__module__}.{fn.__name__} drops active_context — the "
                "chain to the delegated executor is broken"
            )
