"""Channel-aware tool result rendering for lattice tools (all agents).

List mode bounds Channel A/B bodies so memory tools stay usable without
blowing the prompt (Memory Grades design 2026-08-11). Detail mode returns
full raw content (with full_text_ref resolution when archives exist).

Channel B always returns some content + caveat when matches exist —
never count-only-only (e264382 intent; false amnesia was worse).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

from soveryn.agents.aetheria.channels import Channel, classify_channel
from soveryn.agents.aetheria.phrase_renderer import render_phrase
from soveryn.platform.lattice.content_caps import (
    CHANNEL_A_BODY_MAX_CHARS,
    CHANNEL_B_BODY_MAX_CHARS,
    CHANNEL_B_TOOL_TOP_N,
    DETAIL_MODE_MAX_CHARS,
    resolve_full_text_ref,
    truncate_body,
)
from soveryn.platform.lattice.legacy import Node, region_for_node
from soveryn.platform.lattice.provenance import Provenance
from soveryn.platform.lattice.types import Entry

RenderMode = Literal["list", "detail"]

_CAVEAT = (
    "UNVERIFIED — you may reason with this and may cite it "
    "as an unverified memory. Never state it as fact."
)


def classify_and_render(
    nodes: tuple[Node, ...],
    *,
    mode: RenderMode = "list",
    data_root: Path | None = None,
) -> dict[str, Any]:
    """Split nodes into assertable Channel A and labelled Channel B context.

    Channel B returned a COUNT ONLY until 2026-08-03. The intent was to stop
    unverified memory being stated as fact, and it worked — but suppression at
    the storage layer also removed the agent's ability to hold a memory AS
    uncertain. Content is now returned, explicitly typed and caveated.

    As of 2026-08-11 (Memory Grades stop-the-bleed), **list** mode caps how
    many B bodies and how many chars of A/B text ride the tool result, so a
    recent/search call cannot inject multi‑k tokens of residue. Counts still
    cover the full result set. **detail** mode (get_lattice_node) returns the
    full body for deep read.

    Args:
        nodes: Lattice nodes in caller rank order (search rank / recency).
        mode: ``list`` (default, search/recent) or ``detail`` (single lookup).
        data_root: Optional root for full_text_ref archive resolution.
    """
    if mode not in ("list", "detail"):
        raise ValueError(f"mode must be 'list' or 'detail', got {mode!r}")

    if mode == "detail":
        return _render_detail(nodes, data_root=data_root)
    return _render_list(nodes)


def _render_list(nodes: tuple[Node, ...]) -> dict[str, Any]:
    stateable: list[dict[str, Any]] = []
    context_only: list[dict[str, Any]] = []
    uncertain: defaultdict[str, int] = defaultdict(int)
    b_total = 0

    for node in nodes:
        entry = _entry_for_classification(node)
        if classify_channel(entry) is Channel.A:
            # Truncate content before phrase wrap so list mode stays bounded.
            body, truncated, original_chars = truncate_body(
                node.content or "", CHANNEL_A_BODY_MAX_CHARS
            )
            rendered_entry = replace(entry, content=body)
            item: dict[str, Any] = {
                "id": node.id,
                "provenance_class": rendered_entry.provenance.cls.value,  # type: ignore[union-attr]
                "source": rendered_entry.provenance.source,  # type: ignore[union-attr]
                "rendered": render_phrase(rendered_entry),
            }
            if truncated:
                item["truncated"] = True
                item["original_chars"] = original_chars
            stateable.append(item)
        else:
            cls = (
                entry.provenance.cls.value
                if entry.provenance is not None
                else "unprovenanced"
            )
            uncertain[cls] += 1
            b_total += 1
            # Collect all B; apply top-N after the pass so counts stay honest.
            context_only.append(_list_b_item(node, cls, entry))

    omitted = max(0, b_total - CHANNEL_B_TOOL_TOP_N)
    returned_b = context_only[:CHANNEL_B_TOOL_TOP_N]

    return {
        "stateable": stateable,
        "context_only": returned_b,
        "uncertain_count_by_class": dict(uncertain),
        "context_only_returned": len(returned_b),
        "context_only_omitted": omitted,
    }


def _list_b_item(node: Node, cls: str, entry: Entry) -> dict[str, Any]:
    body, truncated, original_chars = truncate_body(
        node.content or "", CHANNEL_B_BODY_MAX_CHARS
    )
    item: dict[str, Any] = {
        "id": node.id,
        "provenance_class": cls,
        "source": (entry.provenance.source if entry.provenance else ""),
        "content": body,
        "caveat": _CAVEAT,
    }
    if truncated:
        item["truncated"] = True
        item["original_chars"] = original_chars
    else:
        item["truncated"] = False
        item["original_chars"] = original_chars
    return item


def _render_detail(
    nodes: tuple[Node, ...],
    *,
    data_root: Path | None,
) -> dict[str, Any]:
    """Single-node (or small set) deep read: raw content + channel labels."""
    stateable: list[dict[str, Any]] = []
    context_only: list[dict[str, Any]] = []
    uncertain: defaultdict[str, int] = defaultdict(int)

    for node in nodes:
        entry = _entry_for_classification(node)
        resolved, content_source, full_text_missing, full_text_ref = _resolve_body(
            node, data_root=data_root
        )
        body, truncated, original_chars = truncate_body(
            resolved, DETAIL_MODE_MAX_CHARS
        )

        if classify_channel(entry) is Channel.A:
            rendered_entry = replace(entry, content=body)
            item: dict[str, Any] = {
                "id": node.id,
                "provenance_class": rendered_entry.provenance.cls.value,  # type: ignore[union-attr]
                "source": rendered_entry.provenance.source,  # type: ignore[union-attr]
                "content": body,
                "rendered": render_phrase(rendered_entry),
                "content_source": content_source,
            }
            if truncated:
                item["truncated"] = True
                item["original_chars"] = original_chars
            if full_text_ref:
                item["full_text_ref"] = full_text_ref
            if full_text_missing:
                item["full_text_missing"] = True
            stateable.append(item)
        else:
            cls = (
                entry.provenance.cls.value
                if entry.provenance is not None
                else "unprovenanced"
            )
            uncertain[cls] += 1
            item = {
                "id": node.id,
                "provenance_class": cls,
                "source": (entry.provenance.source if entry.provenance else ""),
                "content": body,
                "truncated": truncated,
                "original_chars": original_chars,
                "content_source": content_source,
                "caveat": _CAVEAT,
            }
            if full_text_ref:
                item["full_text_ref"] = full_text_ref
            if full_text_missing:
                item["full_text_missing"] = True
            context_only.append(item)

    return {
        "stateable": stateable,
        "context_only": context_only,
        "uncertain_count_by_class": dict(uncertain),
        "context_only_returned": len(context_only),
        "context_only_omitted": 0,
    }


def _resolve_body(
    node: Node,
    *,
    data_root: Path | None,
) -> tuple[str, str, bool, str | None]:
    """Return (body, content_source, full_text_missing, full_text_ref)."""
    ref = None
    if node.provenance and isinstance(node.provenance, dict):
        raw = node.provenance.get("full_text_ref")
        if raw:
            ref = str(raw)

    if ref:
        archived = resolve_full_text_ref(ref, data_root=data_root)
        if archived is not None:
            source = "archive"
            if ref.startswith("thoughts_log:"):
                source = "thoughts_log"
            return archived, source, False, ref
        # Honest miss: lattice head + flag (invariant 4).
        return node.content or "", "lattice", True, ref

    return node.content or "", "lattice", False, None


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
        if "grade" in node.provenance:
            metadata["grade"] = node.provenance["grade"]
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
