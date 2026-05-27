"""V.E.T.T. research surface contract.

Vett owns research workflows. The concrete browser/crawl/research behavior is
ported later; this module only declares the package boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class VettResearchNotPortedError(NotImplementedError):
    """Raised when research execution is requested before the port exists."""


@dataclass(frozen=True)
class ResearchRequest:
    query: str
    constraints: dict[str, Any] | None = None


@dataclass(frozen=True)
class ResearchResult:
    summary: str
    sources: tuple[str, ...] = ()


class VettResearchSurface:
    """Declared V.E.T.T. research entry surface."""

    agent_name = "vett"

    def run(self, request: ResearchRequest) -> ResearchResult:
        raise VettResearchNotPortedError("Vett research behavior is declared, not ported in Phase 1")
