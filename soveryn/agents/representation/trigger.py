"""Eligibility gate for the representation daemon.

Pure function — no I/O, no DB, no time calls. The trigger source (daemon or
future event-driven caller) supplies new_turn_count and config; this module
decides eligible/skip without any side effects.
"""
from __future__ import annotations

from dataclasses import dataclass

from soveryn.agents.representation.config import RepresentationConfig


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    skip_reason: str | None  # "disabled" | "below_min_turns" | None


def evaluate(new_turn_count: int, config: RepresentationConfig) -> Eligibility:
    """Apply eligibility gates in order. First failing gate wins.

    Gates:
      1. disabled  — config.enabled is False
      2. below_min_turns — new_turn_count < config.min_turns

    Parameters
    ----------
    new_turn_count:
        Number of new conversation turns since the last representation run.
    config:
        RepresentationConfig instance (provides enabled + min_turns).

    Returns
    -------
    Eligibility
        eligible=True with skip_reason=None if all gates pass.
        eligible=False with a non-None skip_reason describing the first gate
        that fired.
    """
    if not config.enabled:
        return Eligibility(eligible=False, skip_reason="disabled")

    if new_turn_count < config.min_turns:
        return Eligibility(eligible=False, skip_reason="below_min_turns")

    return Eligibility(eligible=True, skip_reason=None)
