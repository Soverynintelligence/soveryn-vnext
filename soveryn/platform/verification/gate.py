"""The verification gate (Component 3) — the finalization guard + budget.

At final-answer finalization in `AgentLoop`, the gate asks one deterministic
question: *did the model just produce a risky factual claim without consulting
any verification tool this turn?* If so, and budget remains, it HOLDS the answer
(does not emit it), injects a corrective system note routing the model to the
right source, and lets the loop continue for one more round. On budget
exhaustion it downgrades the answer to the honest floor.

Scoping + safety are the loop's responsibility (fail-open try/except, Vett-only
owner set); this module is a PURE decision function plus a small config holder,
so it is trivially testable and cannot itself hang or crash a turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from soveryn.platform.verification.detector import (
    ClaimRiskSignal,
    HeuristicClaimDetector,
    RiskVerdict,
)

# Tools whose invocation this turn counts as "a source was consulted". v1 only
# checks that ONE of these ran — not per-claim attribution (see spec Out of
# scope). Mirrors the design doc's VERIFY_TOOLS set.
VERIFY_TOOLS: frozenset[str] = frozenset({"web_search", "fetch_url", "system_probe"})

# The honest floor: emitted verbatim when the budget is exhausted and the model
# is still trying to state an unsourced claim. Never falls back to the guess.
HONEST_FLOOR_ANSWER: str = (
    "I couldn't verify this and I won't guess. Here's what I can honestly say: "
    "I don't have a confirmed source for those specifics this turn, so I won't "
    "state them as fact. If you'd like, I can try verifying again."
)

# The corrective note injected on a HOLD. Routes host-facts to system_probe and
# external specs to web_search/fetch_url, but does not hard-force which tool —
# the model chooses within the forced-verify round.
_CORRECTIVE_NOTE_TEMPLATE: str = (
    "You are about to state facts you have not verified this turn ({markers}). "
    "Do not answer from memory. Tell the user you're verifying, then call "
    "system_probe (for facts about THIS machine) or web_search/fetch_url (for "
    "external specs), and answer only from the result."
)


@dataclass(frozen=True)
class GateDecision:
    """What the loop should do with the drafted final answer.

    action ∈ {"emit", "hold", "floor"}:
      - "emit"  → emit `answer` unchanged (not risky, or a verify tool ran).
      - "hold"  → do NOT emit; append `note` as a system message and continue
                  the loop for one more (forced-verify) round.
      - "floor" → budget exhausted; emit `answer` (the honest floor) instead of
                  the drafted claim.
    """

    action: str
    verdict: RiskVerdict
    answer: str | None = None
    note: str | None = None


class VerificationGate:
    """Config holder + pure decision function for the finalization guard.

    Owner-scoped: `applies_to(agent)` is True only for agents in `owner_agents`
    (default: Vett only). The loop consults this BEFORE running any gate logic,
    so non-owner turns finalize on the exact pre-gate code path.

    The gate never performs I/O and never raises for ordinary inputs; the loop
    still wraps `evaluate` in try/except so any unexpected error fails open.
    """

    def __init__(
        self,
        *,
        detector: ClaimRiskSignal | None = None,
        owner_agents: frozenset[str] = frozenset({"vett"}),
        forced_verify_budget: int = 2,
        verify_tools: frozenset[str] = VERIFY_TOOLS,
    ) -> None:
        if forced_verify_budget < 0:
            raise ValueError(
                f"forced_verify_budget must be >= 0 (got {forced_verify_budget})"
            )
        self.detector: ClaimRiskSignal = detector or HeuristicClaimDetector()
        self.owner_agents = frozenset(a.lower().strip() for a in owner_agents)
        self.forced_verify_budget = forced_verify_budget
        self.verify_tools = frozenset(verify_tools)

    def applies_to(self, agent_name: str) -> bool:
        """True only for agents this gate governs. v1: Vett only."""
        return (agent_name or "").lower().strip() in self.owner_agents

    def evaluate(
        self,
        *,
        answer_text: str,
        question_text: str,
        tool_ledger: Iterable[str],
        budget: int,
    ) -> GateDecision:
        """Decide what to do with a drafted final answer.

        answer_text   — the model's drafted final content.
        question_text — the user message (passed to the risk signal).
        tool_ledger   — tool NAMES invoked this turn (any order).
        budget        — remaining forced-verify budget for this turn.

        Deterministic logic (spec Component 3):
          not risky            → emit
          a verify tool ran    → emit
          risky ∧ budget > 0   → hold (inject corrective note)
          risky ∧ budget == 0  → floor (honest-floor answer)
        """
        verdict = self.detector.assess(
            answer_text=answer_text, question_text=question_text,
        )
        if not verdict.risky:
            return GateDecision(action="emit", verdict=verdict, answer=answer_text)

        verified_this_turn = any(name in self.verify_tools for name in tool_ledger)
        if verified_this_turn:
            return GateDecision(action="emit", verdict=verdict, answer=answer_text)

        if budget > 0:
            note = _CORRECTIVE_NOTE_TEMPLATE.format(
                markers=", ".join(verdict.markers) or "unverified facts"
            )
            return GateDecision(action="hold", verdict=verdict, note=note)

        return GateDecision(
            action="floor", verdict=verdict, answer=HONEST_FLOOR_ANSWER,
        )
