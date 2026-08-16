"""Pure barge-in / turn-policy decisions (no Pipecat dependency).

PR4a of docs/designs/2026-08-16-duplex-voice-shell.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BargeDecision:
    accept: bool
    reason: str  # accepted | disabled | not_bot_speaking | below_min_barge | already_pending


def should_accept_barge(
    *,
    barge_in_enabled: bool,
    bot_speaking: bool,
    speech_ms: float,
    min_barge_ms: int,
    interrupt_pending: bool = False,
) -> BargeDecision:
    """Whether user speech while bot is speaking should interrupt.

    ``speech_ms`` is continuous VAD-active duration since speech start.
    """
    if not barge_in_enabled:
        return BargeDecision(False, "disabled")
    if interrupt_pending:
        return BargeDecision(False, "already_pending")
    if not bot_speaking:
        return BargeDecision(False, "not_bot_speaking")
    if speech_ms < float(min_barge_ms):
        return BargeDecision(False, "below_min_barge")
    return BargeDecision(True, "accepted")
