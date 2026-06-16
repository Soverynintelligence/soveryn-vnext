"""The why/stance/trigger grammar — a deliberate share's intent header.

Modeled on platform.lattice.provenance.Provenance: a frozen, validated
value object. `stance` is an OPEN vocabulary by design — there is no enum.
A field she names (not a menu she picks from) keeps the act an act of
agency rather than classification.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeliberateShareIntent:
    """Why a thought is being surfaced, now.

    why     — the raw, honest reason; the bridge shown to Jon.
    stance  — the relational function of the share; open vocabulary.
    trigger — a reference to what prompted the surfacing. Never prose at the
              ledger: ledger.resolve_trigger() anchors it to a real node.
    """

    why: str
    stance: str
    trigger: str

    def __post_init__(self) -> None:
        for name in ("why", "stance", "trigger"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
