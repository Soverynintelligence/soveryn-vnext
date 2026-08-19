"""Shared ActTruth gates for unprompted crew ticks (heartbeat, patrol, …).

Every ACTIVE agent has their own budget + ledger stream. Quiet failures and
unprompted spends are per-agent — the whole crew, not only Aetheria.
"""

from __future__ import annotations

import logging
from typing import Any

from acttruth.budget import BudgetDecision
# get_acttruth: late-imported from acttruth.audit

log = logging.getLogger(__name__)

def _at():
    """Resolve ActTruth handle (late import so hosts can patch acttruth.audit.get_acttruth)."""
    from acttruth.audit import get_acttruth
    return get_acttruth()



def apply_budget_to_prompt(
    agent_id: str,
    prompt: str,
    *,
    rail: str,
) -> tuple[str, BudgetDecision | None]:
    """If budget exhausted, append stand-down and ledger a budget_deny.

    Returns (possibly modified prompt, decision or None if acttruth unavailable).
    """
    try:
        acttruth = _at()
        decision = acttruth.budget.check(agent_id)
        if not decision.allowed:
            prompt = prompt + "\n\n" + decision.stand_down_note
            acttruth.ledger.record(
                agent_id=agent_id,
                kind="budget_deny",
                summary=decision.reason or "budget exhausted",
                ok=True,
                action=rail,
                tags=("unprompted", "quiet_is_correct", rail),
            )
        return prompt, decision
    except Exception:
        log.exception(
            "acttruth budget check failed for %s/%s; continuing without gate",
            agent_id,
            rail,
        )
        return prompt, None


def record_unprompted_tick(
    agent_id: str,
    *,
    rail: str,
    tick_id: str,
    action_taken: bool,
    tool_call_count: int = 0,
    note_head: str = "",
    extra_summary: str = "",
) -> None:
    """Ledger the pulse; spend budget only when the agent acted."""
    try:
        acttruth = _at()
        parts = [
            f"{rail} tools={tool_call_count} action_taken={action_taken}",
        ]
        if extra_summary:
            parts.append(extra_summary)
        if note_head.strip():
            parts.append(f"note_head={note_head.strip()[:120]!r}")
        elif not action_taken:
            parts.append("quiet")
        kind = {
            "heartbeat": "heartbeat",
            "patrol": "patrol",
        }.get(rail, "note")
        acttruth.ledger.record(
            agent_id=agent_id,
            kind=kind,  # type: ignore[arg-type]
            summary=" ".join(parts),
            ok=True,
            action=rail,
            tags=(
                ("unprompted", "acted", rail)
                if action_taken
                else ("unprompted", "quiet", rail)
            ),
        )
        if action_taken:
            spent = acttruth.budget.spend(
                agent_id,
                kind=f"{rail}_action",
                summary=f"tick={tick_id} tools={tool_call_count}",
            )
            acttruth.ledger.record(
                agent_id=agent_id,
                kind="budget_spend",
                summary=(
                    f"spent unprompted action on {rail}; "
                    f"remaining={spent.remaining}/{spent.limit}"
                ),
                ok=True,
                action=rail,
                tags=("unprompted", rail),
            )
    except Exception:
        log.exception(
            "acttruth ledger/spend failed for %s/%s; tick unaffected",
            agent_id,
            rail,
        )


# Chat agents + Kernel (HITL tools). Kernel has no unprompted pulse budget,
# but still gets a ledger stream and a CC badge.
CREW_AGENTS: tuple[str, ...] = ("aetheria", "vett", "scotty", "kernel")


def crew_status(*, agents: tuple[str, ...] | None = None, limit: int = 5) -> dict[str, Any]:
    """Snapshot budget + recent events for the whole crew (incl. Kernel)."""
    agents = agents or CREW_AGENTS
    acttruth = _at()
    out: dict[str, Any] = {"root": str(acttruth.root), "agents": {}}
    for agent in agents:
        d = acttruth.budget.check(agent)
        events = acttruth.ledger.recent(agent, limit=limit)
        out["agents"][agent] = {
            "budget": {
                "used": d.used,
                "limit": d.limit,
                "remaining": d.remaining,
                "allowed": d.allowed,
                "reason": d.reason,
            },
            "recent": [e.to_dict() for e in events],
        }
    return out
