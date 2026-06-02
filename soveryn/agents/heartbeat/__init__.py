"""Heartbeat daemon — spontaneous initiation for Aetheria.

Spec: docs/superpowers/specs/2026-06-02-heartbeat.md

Design rules locked (informed by old-SOVERYN heartbeat damage):
- Isolated [heartbeat] aetheria session, NEVER shared with user chat
- Plain text prompts only — no scratchpad markup (collided with TOOL_CALL
  syntax in old SOVERYN, causing both to break under context pressure)
- Tool-mediated output only — heartbeat -> her tools -> coord boards ->
  webhook chain. Never directly injected into user chat
- Recent-activity backoff — don't wake her if she just acted
- Loud kill switch — SOVERYN_HEARTBEAT_ENABLED=false (not a magic interval
  value like old SOVERYN's 99999 hack)
- <300 lines across the whole module (old SOVERYN's heartbeat_integrated.py
  was ~54KB; complexity caused most of the damage)
"""

from soveryn.agents.heartbeat.trigger import (
    HeartbeatConfig,
    SkipReason,
    TickEligibility,
    evaluate_tick,
)
from soveryn.agents.heartbeat.prompt import (
    BoardSnapshot,
    LatticeSnapshot,
    build_heartbeat_prompt,
)


__all__ = [
    "BoardSnapshot",
    "HeartbeatConfig",
    "LatticeSnapshot",
    "SkipReason",
    "TickEligibility",
    "build_heartbeat_prompt",
    "evaluate_tick",
]
