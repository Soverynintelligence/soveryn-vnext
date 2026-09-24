"""Verified execution receipt — chatter cannot mint one of these."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReceiptKind(StrEnum):
    """How the write was earned — not how the model feels about it."""

    GATE_ALLOW = "gate_allow"
    TOOL_OK = "tool_ok"
    USER_REMEMBER = "user_remember"


@dataclass(frozen=True)
class ActionReceipt:
    """Proof a durable lattice write is allowed.

    Gate Allow, a successful tool result, or Jon saying remember.
    Model talk does not produce this object.
    """

    kind: ReceiptKind | str
    source: str
    ref: str = ""

    def __post_init__(self) -> None:
        try:
            kind = self.kind if isinstance(self.kind, ReceiptKind) else ReceiptKind(str(self.kind))
        except ValueError as exc:
            raise ValueError(f"unknown receipt kind: {self.kind!r}") from exc
        object.__setattr__(self, "kind", kind)
        source = (self.source or "").strip()
        if not source:
            raise ValueError("receipt source must be non-empty")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "ref", (self.ref or "").strip())

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": str(self.kind),
            "source": self.source,
            "ref": self.ref,
        }
