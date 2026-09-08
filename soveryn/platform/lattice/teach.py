"""Lattice teach loop — Jon teaches once → shared current house facts.

S1/S2: remember_fact + close_and_supersede. Seat tools call this; models
cannot mint receipts. Layer is always global; node_type is always fact.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from soveryn.platform.lattice.attic import AtticStore
from soveryn.platform.lattice.fact_rail import CANONICAL_FACT_TAG
from soveryn.platform.lattice.legacy import LAYER_GLOBAL, LatticeStore, Node
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass
from soveryn.platform.lattice.receipt import ActionReceipt, ReceiptKind
from soveryn.platform.lattice.types import Region
from soveryn.platform.lattice.writer import LatticeWriter, WriteResult
from soveryn.platform.tools.registry import ToolSpec

HISTORICAL_SNAPSHOT_TAG = "historical_snapshot"
ENTITY_TAG_PREFIX = "entity:"
TEACH_GENERATOR = "teach_loop"


def entity_tag(slug: str) -> str:
    """Normalize entity slug → tag ``entity:<slug>``."""
    cleaned = (slug or "").strip().lower().lstrip(":")
    if cleaned.startswith(ENTITY_TAG_PREFIX):
        cleaned = cleaned[len(ENTITY_TAG_PREFIX) :]
    cleaned = cleaned.strip()
    if not cleaned:
        raise ValueError("entity slug must be non-empty")
    return f"{ENTITY_TAG_PREFIX}{cleaned}"


def find_current_canonical_by_entity(
    lattice_store: LatticeStore,
    entity: str,
) -> Node | None:
    """Current house fact for ``entity:<slug>`` (excludes historical_snapshot)."""
    tag = entity_tag(entity)
    tag_like = f"%{tag}%"
    canon_like = f"%{CANONICAL_FACT_TAG}%"
    with sqlite3.connect(str(lattice_store.db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM nodes "
            "WHERE IFNULL(tags, '[]') LIKE ? "
            "  AND IFNULL(tags, '[]') LIKE ? "
            "  AND IFNULL(tags, '[]') NOT LIKE ? "
            "ORDER BY updated_at DESC LIMIT 8",
            (tag_like, canon_like, f"%{HISTORICAL_SNAPSHOT_TAG}%"),
        ).fetchall()
    # Exact tag match (LIKE is substring; entity:foo must not hit entity:foobar)
    for row in rows:
        node = lattice_store.get_node(row["id"])
        if node is None:
            continue
        if tag in node.tags and CANONICAL_FACT_TAG in node.tags:
            if HISTORICAL_SNAPSHOT_TAG not in node.tags:
                return node
    return None


def close_and_supersede(
    *,
    lattice_store: LatticeStore,
    attic_store: AtticStore,
    agent: str,
    old_id: str,
    new_content: str,
    entity: str | None,
    provenance: Provenance,
    receipt: ActionReceipt,
    embed_fn: Callable[[str], tuple[float, ...]] | None = None,
    confidence: float | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Write new fact, tag old historical_snapshot, edge + representation_log.

    Never mutates old content. Pattern stolen from representation writeback
    ``_supersede`` without importing Conclusion.
    """
    embedding = _maybe_embed(embed_fn, new_content)
    extra = (entity_tag(entity),) if entity else ()
    writer = LatticeWriter(
        lattice_store=lattice_store, attic_store=attic_store, agent=agent
    )
    result = writer.write(
        new_content,
        region=Region.SEMANTIC,
        kind="factual_anchor",
        provenance=provenance,
        confirmed=True,
        receipt=receipt,
        layer=LAYER_GLOBAL,
        node_type="fact",
        extra_tags=extra,
        embedding=embedding,
        on_overflow="raise",
    )
    if result.destination != "lattice" or not result.lattice_id:
        return {
            "ok": False,
            "error": "teach write routed to attic or failed",
            "destination": result.destination,
            "attic_id": result.attic_id,
            "superseded_id": old_id,
        }
    new_id = result.lattice_id
    teach_run = run_id or f"teach:{uuid.uuid4()}"
    conf_to = (
        float(confidence)
        if confidence is not None
        else float(provenance.confidence)
    )
    _supersede_fact(
        lattice_store.db_path,
        old_node_id=old_id,
        new_node_id=new_id,
        new_content=new_content,
        run_id=teach_run,
        confidence_to=conf_to,
    )
    return {
        "ok": True,
        "lattice_id": new_id,
        "superseded_id": old_id,
        "run_id": teach_run,
    }


def remember_fact(
    content: str,
    *,
    entity: str | None = None,
    source: str = "jon",
    as_of: str | None = None,
    replace_entity: bool = True,
    lattice_store: LatticeStore,
    attic_store: AtticStore,
    agent: str = "aetheria",
    embed_fn: Callable[[str], tuple[float, ...]] | None = None,
) -> dict[str, Any]:
    """Teach a house fact onto the global Lattice spine.

    Returns ``{ok, lattice_id, superseded_id?}`` (plus error fields on failure).
    """
    text = (content or "").strip()
    if not text:
        return {"ok": False, "error": "content must be non-empty"}

    source_s = (source or "").strip() or "jon"
    as_of_s = (as_of or "").strip() or datetime.now(timezone.utc).date().isoformat()
    provenance = Provenance(
        ProvenanceClass.TOLD,
        source=source_s,
        confidence=1.0,
        temporal_context=as_of_s,
        generator=TEACH_GENERATOR,
    )
    receipt = ActionReceipt(ReceiptKind.USER_REMEMBER, source=source_s)

    old: Node | None = None
    entity_slug = None
    if entity is not None and str(entity).strip():
        entity_slug = entity_tag(entity)[len(ENTITY_TAG_PREFIX) :]
        if replace_entity:
            old = find_current_canonical_by_entity(lattice_store, entity_slug)

    if old is not None:
        # Idempotent: same content already current → no write
        if (old.content or "").strip() == text:
            return {
                "ok": True,
                "lattice_id": old.id,
                "superseded_id": None,
                "unchanged": True,
            }
        return close_and_supersede(
            lattice_store=lattice_store,
            attic_store=attic_store,
            agent=agent,
            old_id=old.id,
            new_content=text,
            entity=entity_slug,
            provenance=provenance,
            receipt=receipt,
            embed_fn=embed_fn,
        )

    embedding = _maybe_embed(embed_fn, text)
    extra = (entity_tag(entity_slug),) if entity_slug else ()
    writer = LatticeWriter(
        lattice_store=lattice_store, attic_store=attic_store, agent=agent
    )
    result: WriteResult = writer.write(
        text,
        region=Region.SEMANTIC,
        kind="factual_anchor",
        provenance=provenance,
        confirmed=True,
        receipt=receipt,
        layer=LAYER_GLOBAL,
        node_type="fact",
        extra_tags=extra,
        embedding=embedding,
        on_overflow="raise",
    )
    if result.destination != "lattice" or not result.lattice_id:
        return {
            "ok": False,
            "error": "teach write routed to attic or failed",
            "destination": result.destination,
            "attic_id": result.attic_id,
        }
    return {"ok": True, "lattice_id": result.lattice_id, "superseded_id": None}


def build_remember_fact_tool(
    lattice_store: LatticeStore,
    attic_store: AtticStore,
    owner_agent: str,
    embed_fn: Callable[[str], tuple[float, ...]] | None = None,
) -> ToolSpec:
    """Seat tool: remember_fact for Aetheria / Eve (not Kernel in v1)."""

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        content = str(args.get("content") or "")
        entity = args.get("entity")
        entity_s = str(entity).strip() if entity is not None else None
        source = str(args.get("source") or "jon")
        as_of = args.get("as_of")
        as_of_s = str(as_of).strip() if as_of is not None else None
        replace = args.get("replace_entity", True)
        if isinstance(replace, str):
            replace_entity = replace.strip().lower() not in ("0", "false", "no")
        else:
            replace_entity = bool(replace)
        try:
            return remember_fact(
                content,
                entity=entity_s or None,
                source=source,
                as_of=as_of_s,
                replace_entity=replace_entity,
                lattice_store=lattice_store,
                attic_store=attic_store,
                agent=owner_agent,
                embed_fn=embed_fn,
            )
        except Exception as exc:  # noqa: BLE001 — tool surface returns error dict
            return {"ok": False, "error": str(exc)}

    return ToolSpec(
        name="remember_fact",
        owner=owner_agent,
        description=(
            "Teach a durable house fact onto the shared Lattice (global, "
            "canonical_fact). Use when Jon says remember / lock this. "
            "Optional entity slug enables close-and-supersede on replace. "
            "Never silently overwrites — old facts become historical_snapshot."
        ),
        schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "One claim, ≤400 chars.",
                },
                "entity": {
                    "type": "string",
                    "description": "Stable slug e.g. cwg.job.dan_ward",
                },
                "source": {
                    "type": "string",
                    "default": "jon",
                    "description": "Who told us (default jon).",
                },
                "as_of": {
                    "type": "string",
                    "description": "As-of date or short phrase (default today UTC).",
                },
                "replace_entity": {
                    "type": "boolean",
                    "default": True,
                    "description": "If entity exists as current, close-and-supersede.",
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
        handler=handler,
    )


def _maybe_embed(
    embed_fn: Callable[[str], tuple[float, ...]] | None,
    text: str,
) -> tuple[float, ...] | None:
    if embed_fn is None:
        return None
    try:
        return embed_fn(text)
    except Exception:
        return None


def _supersede_fact(
    db_path,
    *,
    old_node_id: str,
    new_node_id: str,
    new_content: str,
    run_id: str,
    confidence_to: float,
) -> None:
    """Tag old historical_snapshot, supersedes edge, representation_log row."""
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(str(db_path)) as con:
        row = con.execute(
            "SELECT tags, content, provenance FROM nodes WHERE id=?",
            (old_node_id,),
        ).fetchone()
        if row is None:
            return
        tags_raw, old_content, old_prov_raw = row
        try:
            existing_tags: list = json.loads(tags_raw) if tags_raw else []
            if not isinstance(existing_tags, list):
                existing_tags = []
        except (json.JSONDecodeError, TypeError):
            existing_tags = []
        if HISTORICAL_SNAPSHOT_TAG not in existing_tags:
            existing_tags.append(HISTORICAL_SNAPSHOT_TAG)
        con.execute(
            "UPDATE nodes SET tags=?, updated_at=? WHERE id=?",
            (json.dumps(existing_tags), now, old_node_id),
        )
        con.execute(
            "INSERT INTO edges (id, source_id, target_id, relationship, "
            "strength, bidirectional, reinforcement_count, reinforced_at, "
            "created_at) VALUES (?, ?, ?, 'supersedes', 1.0, 0, 1, ?, ?)",
            (str(uuid.uuid4()), new_node_id, old_node_id, now, now),
        )
        confidence_from: str | None = None
        try:
            if old_prov_raw:
                old_prov = json.loads(old_prov_raw)
                if isinstance(old_prov, dict) and old_prov.get("confidence") is not None:
                    confidence_from = str(old_prov.get("confidence"))
        except (json.JSONDecodeError, TypeError):
            pass
        old_content_head = (old_content or "")[:200] or None
        new_content_head = (new_content or "")[:200]
        con.execute(
            "INSERT INTO representation_log "
            "(id, old_id, new_id, old_content_head, new_content_head, "
            "driving_premises, confidence_from, confidence_to, run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                old_node_id,
                new_node_id,
                old_content_head,
                new_content_head,
                json.dumps([]),
                confidence_from,
                str(confidence_to),
                run_id,
                now,
            ),
        )
        con.commit()
    try:
        from soveryn.platform.lattice.legacy import _drop_scan_cache
        _drop_scan_cache(db_path)
    except Exception:
        pass
