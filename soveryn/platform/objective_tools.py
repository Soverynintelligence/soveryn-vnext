"""Tools so Aetheria can assign standing objectives (Grok-bot style work)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from soveryn.citizens import commissions
from soveryn.citizens import objectives as objectives_mod
from soveryn.citizens.registry import connect
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec

_DEFAULT_DB = Path.home() / "soveryn_vnext" / "data" / "citizens.db"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _db() -> Path:
    import os
    return Path(os.environ.get("SOVERYN_CITIZENS_DB") or _DEFAULT_DB)


def register_objective_tools(registry: ToolRegistry, *, owner_agent: str) -> None:
    def assign(args: Mapping[str, Any]) -> dict[str, Any]:
        desk = str(args.get("desk") or "").strip().lower()
        title = str(args.get("title") or "").strip()
        brief = str(args.get("brief") or "").strip()
        owner_id = str(args.get("owner_id") or "vett").strip().lower()
        success = str(args.get("success_criteria") or "").strip()
        enqueue = args.get("enqueue", True)
        if isinstance(enqueue, str):
            enqueue = enqueue.strip().lower() not in ("0", "false", "no")
        try:
            with connect(_db()) as conn:
                row = objectives_mod.assign(
                    conn,
                    desk=desk,
                    title=title,
                    brief=brief,
                    at=_now(),
                    owner_id=owner_id,
                    success_criteria=success,
                    assigned_by=owner_agent,
                )
                commission_id = None
                if enqueue:
                    commission_id = commissions.enqueue(
                        conn,
                        row["owner_id"],
                        objectives_mod.research_commission_body(row),
                        at=_now(),
                    )
            return {
                "ok": True,
                "objective_id": row["id"],
                "desk": row["desk"],
                "owner_id": row["owner_id"],
                "state": row["state"],
                "commission_id": commission_id,
                "note": (
                    f"Assigned. {owner_id} will work this as a standing objective "
                    f"(not a one-shot chat). You'll get a brief when it's ready "
                    f"to verify."
                ),
            }
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": repr(exc)}

    def status(args: Mapping[str, Any]) -> dict[str, Any]:
        oid = str(args.get("objective_id") or "").strip()
        desk = str(args.get("desk") or "").strip().lower() or None
        try:
            with connect(_db()) as conn:
                if oid:
                    row = objectives_mod.get(conn, oid)
                    if row is None:
                        return {"ok": False, "error": "not found"}
                    ck = None
                    if row.get("checkpoint_path"):
                        ck = objectives_mod.load_checkpoint(row["checkpoint_path"])
                    return {"ok": True, "objective": row, "checkpoint": ck}
                rows = objectives_mod.list_objectives(
                    conn, desk=desk, limit=int(args.get("limit") or 20)
                )
            return {"ok": True, "objectives": rows, "count": len(rows)}
        except Exception as exc:
            return {"ok": False, "error": repr(exc)}

    registry.register(
        ToolSpec(
            name="objective_assign",
            owner=owner_agent,
            description=(
                "Assign standing work for a business desk (cwg, hl, soveryn) to a "
                "citizen — Grok-bot style: define the objective once, they execute "
                "across waves, you verify when ready. Use when Jon says things like "
                "'research this overnight', 'keep working on CWG pricing', or "
                "'put Vett on a real dig'. Prefer this over one-shot house_post for "
                "multi-step research. Desks: cwg (PondWright/ponds), hl (History's "
                "Ledger), soveryn (house/product)."
            ),
            schema={
                "type": "object",
                "properties": {
                    "desk": {
                        "type": "string",
                        "enum": ["cwg", "hl", "soveryn"],
                    },
                    "title": {"type": "string"},
                    "brief": {"type": "string"},
                    "owner_id": {
                        "type": "string",
                        "enum": ["vett", "eve", "scotty", "kernel"],
                    },
                    "success_criteria": {"type": "string"},
                    "enqueue": {"type": "boolean"},
                },
                "required": ["desk", "title", "brief"],
            },
            handler=assign,
        )
    )
    registry.register(
        ToolSpec(
            name="objective_status",
            owner=owner_agent,
            description=(
                "Check standing objectives — active work, checkpoints, or one "
                "objective by id. Use to answer 'what's Vett working on?' or "
                "'is the CWG research ready?'."
            ),
            schema={
                "type": "object",
                "properties": {
                    "objective_id": {"type": "string"},
                    "desk": {
                        "type": "string",
                        "enum": ["cwg", "hl", "soveryn"],
                    },
                    "limit": {"type": "integer"},
                },
            },
            handler=status,
        )
    )
