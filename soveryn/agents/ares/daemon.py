"""Ares daemon contract.

Ares is a background security daemon, not an LLM chat agent. Production daemon
behavior is ported in a later phase; this module declares the entry surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AresDaemonNotPortedError(NotImplementedError):
    """Raised when Ares execution is requested before the port exists."""


@dataclass(frozen=True)
class AresFinding:
    finding_type: str
    severity: str
    evidence: dict[str, Any]


class AresDaemonSurface:
    """Declared no-LLM security daemon entry surface."""

    agent_name = "ares"
    uses_llm = False

    def scan_once(self) -> tuple[AresFinding, ...]:
        raise AresDaemonNotPortedError("Ares daemon behavior is declared, not ported in Phase 1")
