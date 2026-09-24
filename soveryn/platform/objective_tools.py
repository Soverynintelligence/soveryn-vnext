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
        # Injected by AgentLoop from the live Messages/chat session when absent.
        dm_session_id = str(args.get("dm_session_id") or "").strip() or None
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
                if dm_session_id:
                    row = dict(row)
                    row["dm_session_id"] = dm_session_id
                    # Persist on checkpoint so later waves / CoS can recover it.
                    path = row.get("checkpoint_path") or ""
                    if path:
                        ck = objectives_mod.load_checkpoint(path)
                        ck["dm_session_id"] = dm_session_id
                        objectives_mod.save_checkpoint(path, ck)
                commission_id = None
                if enqueue:
                    commission_id = commissions.enqueue(
                        conn,
                        row["owner_id"],
                        objectives_mod.commission_body_for(row),
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
        state = str(args.get("state") or "").strip().lower() or None
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
                    conn,
                    desk=desk,
                    state=state,
                    limit=int(args.get("limit") or 20),
                )
            return {"ok": True, "objectives": rows, "count": len(rows)}
        except Exception as exc:
            return {"ok": False, "error": repr(exc)}

    def verify(args: Mapping[str, Any]) -> dict[str, Any]:
        """Close the assign→execute→verify loop after Jon reviews."""
        oid = str(args.get("objective_id") or "").strip()
        state = str(args.get("state") or "done").strip().lower()
        note = str(args.get("note") or "").strip()
        if state not in ("done", "failed", "cancelled"):
            return {
                "ok": False,
                "error": "state must be done, failed, or cancelled",
            }
        if not oid:
            return {"ok": False, "error": "objective_id required"}
        try:
            with connect(_db()) as conn:
                row = objectives_mod.get(conn, oid)
                if row is None:
                    return {"ok": False, "error": "not found"}
                prev = row.get("state")
                updated = objectives_mod.set_state(
                    conn, oid, state=state, at=_now()
                )
                path = row.get("checkpoint_path") or ""
                if path and note:
                    ck = objectives_mod.load_checkpoint(path)
                    notes = list(ck.get("notes") or [])
                    notes.append(f"verify:{state}: {note}")
                    ck["notes"] = notes[-40:]
                    ck["verified_at"] = _now()
                    ck["verified_by"] = owner_agent
                    ck["verify_note"] = note
                    objectives_mod.save_checkpoint(path, ck)
                    try:
                        root = Path(path)
                        root.mkdir(parents=True, exist_ok=True)
                        (root / "verify.md").write_text(
                            f"# Verify · {state}\n\n"
                            f"- **by:** {owner_agent}\n"
                            f"- **at:** {_now()}\n"
                            f"- **prior_state:** {prev}\n\n"
                            f"{note}\n",
                            encoding="utf-8",
                        )
                    except OSError:
                        pass
            return {
                "ok": True,
                "objective_id": oid,
                "prior_state": prev,
                "state": updated["state"],
                "note": note or None,
            }
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": str(exc)}
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
                "'put Eve on a real dig'. Prefer this over one-shot house_post for "
                "multi-step research. Desks: cwg (PondWright/ponds — house Apex/AKT "
                "catalogs first, not the open web), hl (History's Ledger), soveryn "
                "(house/product). Owners: eve (research+ship) or kernel (build). "
                "Vett/Scotty are parked. After they finish, check objective_status "
                "and call objective_verify when Jon accepts."
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
                        "enum": ["eve", "kernel"],
                    },
                    "success_criteria": {"type": "string"},
                    "enqueue": {"type": "boolean"},
                    "dm_session_id": {
                        "type": "string",
                        "description": (
                            "Jon DM session to deliver the CoS brief into. "
                            "Usually injected automatically from the live chat."
                        ),
                    },
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
                "'is the CWG research ready?'. Filter with state=ready_for_verify "
                "when looking for work waiting on Jon."
            ),
            schema={
                "type": "object",
                "properties": {
                    "objective_id": {"type": "string"},
                    "desk": {
                        "type": "string",
                        "enum": ["cwg", "hl", "soveryn"],
                    },
                    "state": {
                        "type": "string",
                        "enum": [
                            "active",
                            "blocked",
                            "ready_for_verify",
                            "done",
                            "failed",
                            "cancelled",
                        ],
                    },
                    "limit": {"type": "integer"},
                },
            },
            handler=status,
        )
    )
    registry.register(
        ToolSpec(
            name="objective_verify",
            owner=owner_agent,
            description=(
                "Close standing objective work after Jon reviews the brief — the "
                "verify step in assign→execute→verify. Call when Jon says the "
                "research is good enough (state=done), wrong/incomplete "
                "(state=failed), or drop it (state=cancelled). Prefer this over "
                "leaving objectives stuck in ready_for_verify."
            ),
            schema={
                "type": "object",
                "properties": {
                    "objective_id": {"type": "string"},
                    "state": {
                        "type": "string",
                        "enum": ["done", "failed", "cancelled"],
                    },
                    "note": {
                        "type": "string",
                        "description": "One-line verify note for the desk record.",
                    },
                },
                "required": ["objective_id", "state"],
            },
            handler=verify,
        )
    )
