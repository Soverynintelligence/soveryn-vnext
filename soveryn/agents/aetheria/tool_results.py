"""Channel-aware tool result rendering for Aetheria lattice tools.

Channel B content is never returned. Tool handlers dispatch through this
module so active lattice reads preserve the Phase 2b-ii speech boundary.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

from soveryn.agents.aetheria.channels import Channel, classify_channel
from soveryn.agents.aetheria.phrase_renderer import render_phrase
from soveryn.platform.lattice.legacy import Node, region_for_node
from soveryn.platform.lattice.provenance import Provenance
from soveryn.platform.lattice.types import Entry


def classify_and_render(nodes: tuple[Node, ...]) -> dict[str, Any]:
    """Split nodes into stateable Channel A entries and count-only Channel B."""

    stateable: list[dict[str, Any]] = []
    uncertain: defaultdict[str, int] = defaultdict(int)

    for node in nodes:
        entry = _entry_for_classification(node)
        if classify_channel(entry) is Channel.A:
            rendered_entry = replace(entry, content=node.content)
            stateable.append(
                {
                    "id": node.id,
                    "provenance_class": rendered_entry.provenance.cls.value,
                    "source": rendered_entry.provenance.source,
                    "rendered": render_phrase(rendered_entry),
                }
            )
        else:
            cls = entry.provenance.cls.value if entry.provenance is not None else "unprovenanced"
            uncertain[cls] += 1

    return {
        "stateable": stateable,
        "uncertain_count_by_class": dict(uncertain),
    }


def _entry_for_classification(node: Node) -> Entry:
    provenance = _provenance_from_payload(node.provenance)
    metadata: dict[str, Any] = {
        "legacy_type": node.type,
        "layer": node.layer,
        "agent": node.agent,
        "salience": node.salience,
        "intensity": node.intensity,
        "access_count": node.access_count,
        "tags": list(node.tags),
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }
    if node.provenance is not None:
        metadata["provenance"] = dict(node.provenance)
        if node.provenance.get("canonical") is False:
            metadata["canonical"] = False
    if node.intent is not None:
        metadata["intent"] = node.intent

    return Entry(
        id=node.id,
        content="",
        region=region_for_node(node),
        source="legacy_lattice",
        metadata=metadata,
        private=node.layer == "private",
        provenance=provenance,
    )


def _provenance_from_payload(payload: dict | None) -> Provenance | None:
    if payload is None:
        return None

    cls = payload.get("cls") or payload.get("class")
    source = payload.get("source", "")
    if not cls or not source:
        return None

    try:
        return Provenance(
            cls=cls,
            source=str(source),
            confidence=payload.get("confidence", 1.0),
            temporal_context=str(payload.get("temporal_context", "")),
            generator=str(payload.get("generator", "lattice_tool")),
            chain=tuple(payload.get("chain", ())),
            derived_from=tuple(payload.get("derived_from", ())),
        )
    except ValueError:
        return None
