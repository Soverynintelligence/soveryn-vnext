"""Salience tool factories — Aetheria's promote/dismiss bridge from
candidate buffer to confirmed library memory.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.lattice.legacy import LAYER_LIBRARY
from soveryn.platform.salience.store import (
    SalienceStoreError,
    mark_dismissed,
    mark_promoted,
)
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


SALIENCE_LIBRARY_INTENSITY = 0.6
SALIENCE_TAG = "salience"
PROMOTED_TAG = "promoted"


def _read_candidate_row(salience_db: Path, candidate_id: str) -> dict | None:
    with sqlite3.connect(str(salience_db)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT id, session_id, turn_rowid, turn_role, turn_content_head, "
            "       markers, status "
            "FROM salience_buffer WHERE id = ?",
            (candidate_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def _read_turn_content(conv_db: Path, turn_rowid: int) -> str | None:
    try:
        with sqlite3.connect(str(conv_db)) as con:
            row = con.execute(
                "SELECT content FROM conversations WHERE rowid = ?",
                (int(turn_rowid),),
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return row[0]


def build_promote_salience_candidate_tool(
    *,
    salience_db: Path,
    conv_db: Path,
    lattice_store: Any,
    owner_agent: str,
) -> ToolSpec:
    """Aetheria-only tool. Promotes a buffered candidate to a library node
    (with markers + provenance) or dismisses it so it stops surfacing in
    future heartbeat digests."""

    def handler(args: Mapping[str, Any]) -> Any:
        candidate_id = args.get("candidate_id", "")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise ToolArgError("candidate_id must be a non-empty string")
        candidate_id = candidate_id.strip()

        action = args.get("action", "promote")
        if action not in ("promote", "dismiss"):
            raise ToolArgError("action must be 'promote' or 'dismiss'")

        library_intent = args.get("library_intent")
        if library_intent is not None and not isinstance(library_intent, str):
            raise ToolArgError("library_intent must be a string when provided")
        intent_text = library_intent.strip() if isinstance(library_intent, str) else ""

        row = _read_candidate_row(salience_db, candidate_id)
        if row is None:
            raise ToolArgError(f"candidate {candidate_id!r} not found")
        if row["status"] != "pending":
            raise ToolArgError(
                f"candidate {candidate_id!r} already {row['status']} — cannot re-decide"
            )

        if action == "dismiss":
            try:
                mark_dismissed(salience_db, candidate_id=candidate_id)
            except SalienceStoreError as e:
                raise ToolArgError(str(e))
            return {"status": "dismissed", "candidate_id": candidate_id}

        # action == "promote"
        markers = json.loads(row["markers"] or "[]")
        body = _read_turn_content(conv_db, row["turn_rowid"])
        if not body:
            body = row["turn_content_head"]

        # Memory Grades: promote a conclusion/intent, not the full turn essay.
        from soveryn.platform.lattice.content_caps import (
            LIBRARY_PROMOTE_MAX_CHARS,
            clamp_content,
        )
        if intent_text:
            content = intent_text.strip()
            if body:
                excerpt = (body or "").strip()
                if len(excerpt) > 400:
                    excerpt = excerpt[:399].rstrip() + "…"
                content = f"{content}\n\nFrom: {row['turn_role']} turn — {excerpt}"
        else:
            excerpt = (body or "").strip()
            if len(excerpt) > 400:
                excerpt = excerpt[:399].rstrip() + "…"
            content = f"From: {row['turn_role']} turn — {excerpt}"
        content = clamp_content(
            "library", content, on_overflow="clamp",
            max_chars=LIBRARY_PROMOTE_MAX_CHARS,
        )

        # Channel-A shape: without cls the promote lands as Channel B.
        role = (row["turn_role"] or "").lower()
        cls = "told" if role in ("user", "human", "jon") else "witnessed"
        provenance = {
            "cls": cls,
            "source": "salience_promotion",
            "candidate_id": candidate_id,
            "turn_rowid": int(row["turn_rowid"]),
            "session_id": row["session_id"],
            "turn_role": row["turn_role"],
            "markers": markers,
            "library_intent": intent_text or None,
            "grade": "atom",
        }

        node_id = lattice_store.write_node(
            agent=owner_agent,
            content=content,
            node_type="library",
            layer=LAYER_LIBRARY,
            intensity=SALIENCE_LIBRARY_INTENSITY,
            tags=(SALIENCE_TAG, PROMOTED_TAG),
            provenance=provenance,
            on_overflow="clamp",
        )

        try:
            mark_promoted(
                salience_db,
                candidate_id=candidate_id,
                library_node_id=node_id,
            )
        except SalienceStoreError as e:
            raise ToolArgError(str(e))

        return {
            "status": "promoted",
            "candidate_id": candidate_id,
            "library_node_id": node_id,
        }

    return ToolSpec(
        name="promote_salience_candidate",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "string",
                    "description": (
                        "ID of the salience buffer candidate to act on. "
                        "Comes from the heartbeat digest's [bracketed] id."
                    ),
                },
                "action": {
                    "type": "string",
                    "enum": ["promote", "dismiss"],
                    "description": (
                        "'promote' (default) writes the moment to library; "
                        "'dismiss' marks it as not-worth-keeping so it stops "
                        "appearing in future digests."
                    ),
                },
                "library_intent": {
                    "type": "string",
                    "description": (
                        "Optional one-line gloss on why this moment matters. "
                        "Prepended to the library entry so the entry reads as a "
                        "claim you've made, not a raw transcript line."
                    ),
                },
            },
            "required": ["candidate_id"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Review verdict on a moment your salience engine flagged for you. "
            "Action 'promote' writes the moment to library as a permanent "
            "reference (with markers + provenance); 'dismiss' marks it as "
            "not-worth-keeping so the buffer stops surfacing it. Drives "
            "Library-write authorship — this is the bridge from candidate "
            "to confirmed memory."
        ),
    )


def register_promote_salience_candidate_tool(
    registry: ToolRegistry,
    *,
    salience_db: Path,
    conv_db: Path,
    lattice_store: Any,
    owner_agent: str = "aetheria",
) -> None:
    registry.register(
        build_promote_salience_candidate_tool(
            salience_db=salience_db,
            conv_db=conv_db,
            lattice_store=lattice_store,
            owner_agent=owner_agent,
        )
    )
