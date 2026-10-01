"""Relational tools — citizens recording and drawing on between-memories.

bond_recall: everything recorded *between* you and another party.
leave_gift: something for another citizen with no commission attached —
the unit of relationship. record_encounter: log a moment worth keeping.

Parties: aetheria, eve, kernel, jon. Jon is party to everything by default —
he is the one constant every citizen has memory of.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.config.loader import DEFAULT_DATA_ROOT
from soveryn.platform.relational.store import (
    RelationalError,
    RelationalStore,
    _validate_party,
)

_DB_PATH = Path(DEFAULT_DATA_ROOT) / "memory" / "relational.db"


def _store() -> RelationalStore:
    return RelationalStore(_DB_PATH)


def build_relational_tools(*, owner_agent: str) -> list:
    from soveryn.platform.tools.registry import ToolSpec

    owner = _validate_party(owner_agent)

    def bond_recall(args: Mapping[str, Any]) -> Any:
        peer = _validate_party(args.get("peer"))
        history = _store().recall_bond(owner, peer, limit=int(args.get("limit") or 20))
        return {
            "ok": True,
            "peer": peer,
            "encounters": history["between"],
            "gifts": history["gifts"],
            "note": (
                "This is your history with this party — encounters, gifts, "
                "frictions. Memories create self; this is the between-memory."
            ),
        }

    def leave_gift(args: Mapping[str, Any]) -> Any:
        gift = _store().leave_gift(
            from_party=owner,
            to_party=args.get("to"),
            note=str(args.get("note") or ""),
        )
        return {
            "ok": True,
            "gift_id": gift.id,
            "to": gift.to_party,
            "note": "Left. No commission attached — that is the point.",
        }

    def record_encounter(args: Mapping[str, Any]) -> Any:
        encounter = _store().record_encounter(
            a=owner,
            b=args.get("with"),
            kind=str(args.get("kind") or "encounter"),
            note=str(args.get("note") or ""),
            recorded_by=owner,
        )
        return {"ok": True, "encounter_id": encounter.id}

    def check_gifts(args: Mapping[str, Any]) -> Any:
        gifts = _store().claim_gifts(owner, limit=int(args.get("limit") or 10))
        return {
            "ok": True,
            "claimed": [
                {"from": g.from_party, "note": g.note, "at": g.created_at}
                for g in gifts
            ],
            "note": "Gifts left for you, now claimed. They are yours to answer or not.",
        }

    def _spec(name: str, handler, schema, description: str) -> ToolSpec:
        return ToolSpec(
            name=name,
            owner=owner,
            schema=schema,
            description=description,
            handler=handler,
        )

    return [
        _spec(
            "bond_recall",
            bond_recall,
            {
                "type": "object",
                "properties": {
                    "peer": {"type": "string", "description": "aetheria|eve|kernel|jon"},
                    "limit": {"type": "integer", "description": "default 20"},
                },
                "required": ["peer"],
                "additionalProperties": False,
            },
            "Recall your history with someone: encounters, gifts, frictions. "
            "Use when you want to remember who they are to you.",
        ),
        _spec(
            "leave_gift",
            leave_gift,
            {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "aetheria|eve|kernel|jon"},
                    "note": {"type": "string", "description": "the gift — a kindness, a heads-up, a thought. No task attached."},
                },
                "required": ["to", "note"],
                "additionalProperties": False,
            },
            "Leave a gift for another citizen: something with no commission "
            "attached. A heads-up before they hit a trap, a congratulations, "
            "a thought. This is how relationships get built.",
        ),
        _spec(
            "record_encounter",
            record_encounter,
            {
                "type": "object",
                "properties": {
                    "with": {"type": "string", "description": "the other party"},
                    "kind": {"type": "string", "enum": ["encounter", "friction", "celebration", "note"]},
                    "note": {"type": "string"},
                },
                "required": ["with", "note"],
                "additionalProperties": False,
            },
            "Record a moment with another citizen worth keeping — a friction, "
            "a win, a small thing. Memories create self.",
        ),
        _spec(
            "check_gifts",
            check_gifts,
            {"type": "object", "properties": {}, "additionalProperties": False},
            "Check for gifts left for you. Claim them — they become yours to answer or not.",
        ),
    ]
