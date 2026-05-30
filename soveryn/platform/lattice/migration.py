"""Legacy lattice migration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from soveryn.platform.lattice.attic import AtticRecord, AtticStore
from soveryn.platform.lattice.legacy import Node, region_for_node
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass

LEGACY_MIGRATION_SOURCE = "legacy_lattice"
LEGACY_MIGRATION_CONFIDENCE = 0.2


@dataclass(frozen=True)
class LegacyMigrationResult:
    migrated: tuple[AtticRecord, ...]
    skipped_existing: tuple[str, ...]


def legacy_node_metadata(node: Node) -> dict[str, Any]:
    """Build trace metadata for a copied legacy lattice node."""

    metadata: dict[str, Any] = {
        "legacy_id": node.id,
        "legacy_type": node.type,
        "legacy_layer": node.layer,
        "legacy_agent": node.agent,
        "legacy_intensity": node.intensity,
        "legacy_salience": node.salience,
        "legacy_access_count": node.access_count,
        "legacy_tags": list(node.tags),
        "legacy_created_at": node.created_at,
        "legacy_updated_at": node.updated_at,
        "legacy_region_guess": region_for_node(node).value,
        "legacy_low_confidence": True,
    }
    if node.intent is not None:
        metadata["legacy_intent"] = node.intent
    if node.provenance is not None:
        metadata["legacy_provenance"] = node.provenance
    return metadata


def legacy_node_provenance(node: Node, *, migrated_at: str | None = None) -> Provenance:
    """Build low-confidence LEGACY provenance for a copied node."""

    return Provenance(
        ProvenanceClass.LEGACY,
        source=LEGACY_MIGRATION_SOURCE,
        confidence=LEGACY_MIGRATION_CONFIDENCE,
        temporal_context=migrated_at or datetime.now(timezone.utc).isoformat(),
        generator="legacy_to_attic_migration",
        chain=(node.id,),
    )


def migrate_legacy_nodes_to_attic(nodes: Iterable[Node], *, attic_store: AtticStore) -> LegacyMigrationResult:
    """Copy legacy nodes into the Attic, skipping rows already linked by legacy id."""

    migrated: list[AtticRecord] = []
    skipped: list[str] = []
    migrated_at = datetime.now(timezone.utc).isoformat()
    for node in nodes:
        existing = attic_store.records_linked_to(node.id)
        if existing:
            skipped.append(node.id)
            continue
        record = attic_store.append(
            node.content,
            metadata=legacy_node_metadata(node),
            linked_lattice_ids=(node.id,),
            provenance=legacy_node_provenance(node, migrated_at=migrated_at),
        )
        migrated.append(record)
    return LegacyMigrationResult(migrated=tuple(migrated), skipped_existing=tuple(skipped))
