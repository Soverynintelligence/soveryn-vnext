"""Scotty repair surface contract.

Scotty is the bounded repair executor. Actual recipe execution is deferred until
the platform repair grammar and supervisor budgets exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RepairTier = Literal["A", "B", "C"]


class ScottyRepairNotPortedError(NotImplementedError):
    """Raised when repair execution is requested before the port exists."""


@dataclass(frozen=True)
class RepairRequest:
    recipe_name: str
    tier: RepairTier
    evidence: dict[str, Any]


@dataclass(frozen=True)
class RepairResult:
    ok: bool
    detail: str


class ScottyRepairSurface:
    """Declared bounded repair entry surface."""

    agent_name = "scotty"

    def execute(self, request: RepairRequest) -> RepairResult:
        raise ScottyRepairNotPortedError("Scotty repair behavior is declared, not ported in Phase 1")
