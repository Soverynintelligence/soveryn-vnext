"""Two-channel recall context assembly for Aetheria."""

from __future__ import annotations

from collections.abc import Iterable

from soveryn.agents.aetheria.channels import Channel, classify_channel
from soveryn.agents.aetheria.phrase_renderer import render_phrase
from soveryn.agents.aetheria.uncertainty_renderer import render_uncertainty
from soveryn.memory.lattice import Node, region_for_node
from soveryn.platform.lattice.fact_rail import merge_fact_rail
from soveryn.platform.lattice.provenance import Provenance
from soveryn.platform.lattice.types import Entry

QUOTABLE_RECALL_HEADING = "Stateable recall:"
LOCKED_FACTS_HEADING = "Locked facts:"
UNCERTAINTY_HEADING = "Uncertain context:"


def assemble_ranked_recall(
    ranked_nodes: Iterable[tuple[Node, float]],
    *,
    identity_nodes: Iterable[Node] = (),
    fact_nodes: Iterable[Node] = (),
) -> str:
    """Assemble live recall from scored Lattice nodes plus reviewed identity spine.

    Scored legacy nodes keep their content non-quotable unless they carry valid
    Channel-A provenance. Reviewed identity-spine nodes are supplied separately
    because they are canonical but may not have embeddings yet.

    ``fact_nodes`` are the locked fact rail — listed first so cosine ranking
    cannot bury phones, dates, names, or negations.
    """

    facts, rest = merge_fact_rail(tuple(ranked_nodes), tuple(fact_nodes))
    sections: list[str] = []
    if facts:
        fact_lines = [LOCKED_FACTS_HEADING]
        fact_lines.extend(f"- {_truncate_fact(node.content)}" for node in facts)
        sections.append("\n".join(fact_lines))
    entries: list[Entry] = []
    for node, score in rest:
        entries.append(_entry_from_node(node, score=score))
    for node in identity_nodes:
        entries.append(_entry_from_node(node, score=None))
    assembled = assemble_recall(entries)
    if assembled:
        sections.append(assembled)
    return "\n\n".join(sections)


def _truncate_fact(text: str, limit: int = 240) -> str:
    flat = text.replace("\n", " ").replace("\r", " ").strip()
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3] + "..."


def assemble_recall(entries: Iterable[Entry]) -> str:
    """Assemble a deterministic two-channel recall context from supplied entries."""

    channel_a: list[Entry] = []
    channel_b: list[Entry] = []
    for entry in entries:
        if classify_channel(entry) is Channel.A:
            channel_a.append(entry)
        else:
            channel_b.append(entry)

    sections: list[str] = []
    if channel_a:
        sections.append(_render_quotable_section(channel_a))

    uncertainty = render_uncertainty(channel_b)
    if uncertainty:
        sections.append(f"{UNCERTAINTY_HEADING}\n- {uncertainty}")

    return "\n\n".join(sections)


def _render_quotable_section(entries: list[Entry]) -> str:
    lines = [QUOTABLE_RECALL_HEADING]
    lines.extend(f"- {render_phrase(entry)}" for entry in entries)
    return "\n".join(lines)


def _entry_from_node(node: Node, *, score: float | None) -> Entry:
    metadata = {
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
    if score is not None:
        metadata["score"] = score
    if node.intent is not None:
        metadata["intent"] = node.intent
    if node.provenance is not None:
        metadata["provenance"] = node.provenance
        # Grade / canonical live on the provenance blob — copy for classify_channel.
        if isinstance(node.provenance, dict):
            if "grade" in node.provenance:
                metadata["grade"] = node.provenance["grade"]
            if node.provenance.get("canonical") is False:
                metadata["canonical"] = False
    return Entry(
        id=node.id,
        content=node.content,
        region=region_for_node(node),
        source="legacy_lattice",
        metadata=metadata,
        private=node.layer == "private",
        provenance=_provenance_from_node(node),
    )


def _provenance_from_node(node: Node) -> Provenance | None:
    raw = node.provenance
    if not isinstance(raw, dict) or "cls" not in raw:
        return None
    try:
        return Provenance(
            raw["cls"],
            source=str(raw["source"]),
            confidence=float(raw["confidence"]),
            temporal_context=str(raw["temporal_context"]),
            generator=str(raw["generator"]),
            chain=tuple(raw.get("chain") or ()),
            derived_from=tuple(raw.get("derived_from") or ()),
        )
    except (KeyError, TypeError, ValueError):
        return None
