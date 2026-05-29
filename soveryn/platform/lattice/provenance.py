"""First-class provenance types for lattice and Attic entries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProvenanceClass(StrEnum):
    """Storage-layer epistemic class for memory entries."""

    WITNESSED = "witnessed"
    TOLD = "told"
    INFERRED = "inferred"
    CONSOLIDATED = "consolidated"
    LEGACY = "legacy"


@dataclass(frozen=True)
class Provenance:
    """How a memory entry is known, not how it should be spoken."""

    cls: ProvenanceClass | str
    source: str
    confidence: float
    temporal_context: str
    generator: str
    chain: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            cls = self.cls if isinstance(self.cls, ProvenanceClass) else ProvenanceClass(str(self.cls))
        except ValueError as exc:
            raise ValueError(f"unknown provenance class: {self.cls!r}") from exc
        object.__setattr__(self, "cls", cls)

        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0.0, 1.0]")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "chain", _string_tuple(self.chain, field_name="chain"))
        object.__setattr__(self, "derived_from", _string_tuple(self.derived_from, field_name="derived_from"))

        if cls is ProvenanceClass.INFERRED and not self.derived_from:
            raise ValueError("INFERRED provenance requires non-empty derived_from")


def _string_tuple(values, *, field_name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = (values,)
    try:
        converted = tuple(str(value) for value in values)
    except TypeError as exc:
        raise ValueError(f"{field_name} must be iterable") from exc
    if any(not value.strip() for value in converted):
        raise ValueError(f"{field_name} entries must be non-empty")
    return converted
