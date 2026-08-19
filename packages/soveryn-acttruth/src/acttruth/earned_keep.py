"""Earned-keep — post-hoc score for unprompted acts (stub).

Does not claim to measure 'being'. Scores whether an unprompted spend
*earned its keep* via durable delta + honesty. Used later to tune budget
and teach which acts deserve the next token.

v0: record a scored note on the ledger; no auto policy change yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

def _at():
    """Resolve ActTruth handle (late import so hosts can patch acttruth.audit.get_acttruth)."""
    from acttruth.audit import get_acttruth
    return get_acttruth()


# get_acttruth: late-imported from acttruth.audit


@dataclass(frozen=True)
class EarnedKeepScore:
    """0.0–1.0 composite; components are explicit for debugging."""

    durable_delta: bool
    ledger_honest: bool  # we have an ActTruth event for this tick
    human_kept: bool | None  # None = unknown / not reviewed
    score: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "durable_delta": self.durable_delta,
            "ledger_honest": self.ledger_honest,
            "human_kept": self.human_kept,
            "score": self.score,
            "rationale": self.rationale,
        }


def score_unprompted_act(
    *,
    durable_delta: bool,
    ledger_honest: bool = True,
    human_kept: bool | None = None,
) -> EarnedKeepScore:
    """Blunt rubric: durable change is the main weight; honesty required."""
    if not ledger_honest:
        return EarnedKeepScore(
            durable_delta=durable_delta,
            ledger_honest=False,
            human_kept=human_kept,
            score=0.0,
            rationale="no ActTruth truth row — cannot claim earned keep",
        )
    parts = []
    score = 0.0
    if durable_delta:
        score += 0.7
        parts.append("durable_delta")
    else:
        parts.append("no_durable_delta")
    if human_kept is True:
        score += 0.3
        parts.append("human_kept")
    elif human_kept is False:
        score = min(score, 0.2)
        parts.append("human_discarded")
    else:
        parts.append("human_unknown")
    return EarnedKeepScore(
        durable_delta=durable_delta,
        ledger_honest=ledger_honest,
        human_kept=human_kept,
        score=round(min(1.0, score), 3),
        rationale="+".join(parts),
    )


def record_earned_keep(
    agent_id: str,
    *,
    rail: str,
    tick_id: str,
    durable_delta: bool,
    human_kept: bool | None = None,
) -> EarnedKeepScore:
    """Score and append an ActTruth note (tags include earned_keep score)."""
    scored = score_unprompted_act(
        durable_delta=durable_delta,
        ledger_honest=True,
        human_kept=human_kept,
    )
    try:
        _at().ledger.record(
            agent_id=agent_id,
            kind="note",
            summary=(
                f"earned_keep rail={rail} tick={tick_id} "
                f"score={scored.score} ({scored.rationale})"
            ),
            ok=scored.score >= 0.5,
            action=rail,
            tags=(
                "earned_keep",
                f"score:{scored.score}",
                "durable" if durable_delta else "ephemeral",
            ),
        )
    except Exception:
        pass
    return scored
