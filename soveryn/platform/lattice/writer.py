"""Provenance-aware lattice write path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from soveryn.platform.lattice.attic import AtticStore
from soveryn.platform.lattice.fact_rail import CANONICAL_FACT_TAG
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.lattice.provenance import Provenance
from soveryn.platform.lattice.receipt import ActionReceipt, ReceiptKind
from soveryn.platform.lattice.types import Region
from soveryn.platform.lattice.write_gate import WriteDecision, classify_write


@dataclass(frozen=True)
class WriteResult:
    destination: str
    lattice_id: str | None = None
    attic_id: str | None = None


class LatticeWriter:
    """Canonical writer that enforces the Phase 2b-i write gate."""

    def __init__(self, *, lattice_store: LatticeStore, attic_store: AtticStore, agent: str = "aetheria") -> None:
        self.lattice_store = lattice_store
        self.attic_store = attic_store
        self.agent = agent

    def write(
        self,
        content: str,
        *,
        region: Region,
        kind: str,
        provenance: Provenance,
        confirmed: bool = False,
        receipt: ActionReceipt | None = None,
    ) -> WriteResult:
        normalized_region = region if isinstance(region, Region) else Region(str(region))
        decision = classify_write(region=normalized_region, kind=kind)
        earned = _earned_receipt(confirmed=confirmed, receipt=receipt)
        if earned is None:
            record = self.attic_store.append(
                content,
                metadata={
                    "pending_receipt": True,
                    "intended_region": normalized_region.value,
                    "write_kind": kind,
                },
                provenance=provenance,
            )
            return WriteResult(destination="attic", attic_id=record.id)
        if decision is WriteDecision.CONFIRM and not confirmed:
            record = self.attic_store.append(
                content,
                metadata={
                    "pending_confirmation": True,
                    "intended_region": normalized_region.value,
                    "write_kind": kind,
                    "receipt": earned.as_dict(),
                },
                provenance=provenance,
            )
            return WriteResult(destination="attic", attic_id=record.id)

        tags = (CANONICAL_FACT_TAG,) if _normalize_kind(kind) == "factual_anchor" else ()
        node_id = self.lattice_store.write_node(
            self.agent,
            content,
            node_type=normalized_region.value,
            tags=tags or None,
            provenance=_provenance_payload(
                provenance,
                confirmed=confirmed,
                confirmation_required=decision is WriteDecision.CONFIRM,
                write_kind=kind,
                receipt=earned,
            ),
        )
        return WriteResult(destination="lattice", lattice_id=node_id)


def write(
    content: str,
    *,
    region: Region,
    kind: str,
    provenance: Provenance,
    confirmed: bool = False,
    receipt: ActionReceipt | None = None,
    lattice_store: LatticeStore,
    attic_store: AtticStore,
    agent: str = "aetheria",
) -> WriteResult:
    writer = LatticeWriter(lattice_store=lattice_store, attic_store=attic_store, agent=agent)
    return writer.write(
        content,
        region=region,
        kind=kind,
        provenance=provenance,
        confirmed=confirmed,
        receipt=receipt,
    )


def _earned_receipt(*, confirmed: bool, receipt: ActionReceipt | None) -> ActionReceipt | None:
    if receipt is not None:
        return receipt
    if confirmed:
        return ActionReceipt(ReceiptKind.USER_REMEMBER, source="jon")
    return None


def _normalize_kind(kind: str) -> str:
    return kind.strip().lower().replace("-", "_").replace(" ", "_")


def _provenance_payload(
    provenance: Provenance,
    *,
    confirmed: bool,
    confirmation_required: bool,
    write_kind: str,
    receipt: ActionReceipt,
) -> dict[str, Any]:
    return {
        "cls": provenance.cls.value,
        "source": provenance.source,
        "confidence": provenance.confidence,
        "temporal_context": provenance.temporal_context,
        "generator": provenance.generator,
        "chain": list(provenance.chain),
        "derived_from": list(provenance.derived_from),
        "confirmed": confirmed,
        "confirmation_required": confirmation_required,
        "write_kind": write_kind,
        "receipt": receipt.as_dict(),
    }
