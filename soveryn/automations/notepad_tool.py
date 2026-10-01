"""cron_notepad — per-automation KV scratchpad for scheduled jobs."""
from __future__ import annotations

import contextvars
from collections.abc import Mapping
from typing import Any

from soveryn.automations import memory as cron_memory
from soveryn.platform.tools.registry import ToolArgError, ToolSpec

current_automation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "automation_notepad_id", default=None
)


def _job_id(args: Mapping[str, Any]) -> str:
    explicit = args.get("automation_id")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    bound = current_automation_id.get()
    if bound:
        return bound
    raise ToolArgError(
        "automation_id required when not running inside a scheduled job"
    )


def build_cron_notepad_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        action = (args.get("action") or "").strip().lower()
        if action not in {"list", "get", "set", "delete"}:
            raise ToolArgError("action must be list, get, set, or delete")
        job_id = _job_id(args)
        if action == "list":
            notes = cron_memory.list_notes(job_id)
            return {"ok": True, "automation_id": job_id, "notes": notes}
        key = args.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ToolArgError("key is required for get/set/delete")
        key = key.strip()
        if action == "get":
            value = cron_memory.get_note(job_id, key)
            return {"ok": True, "automation_id": job_id, "key": key, "value": value}
        if action == "delete":
            deleted = cron_memory.delete_note(job_id, key)
            return {
                "ok": deleted,
                "automation_id": job_id,
                "key": key,
                "deleted": deleted,
            }
        value = args.get("value")
        if not isinstance(value, str):
            raise ToolArgError("value is required for set")
        return {"ok": True, **cron_memory.set_note(job_id, key, value)}

    return ToolSpec(
        name="cron_notepad",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "set", "delete"],
                    "description": (
                        "list keys, get one, set one, or delete one. "
                        "Survives across scheduled runs of this automation."
                    ),
                },
                "key": {"type": "string", "description": "Required for get/set/delete."},
                "value": {"type": "string", "description": "Required for set."},
                "automation_id": {
                    "type": "string",
                    "description": (
                        "Defaults to the currently firing job. Pass explicitly "
                        "only when editing another job's pad."
                    ),
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Per-job durable notepad for scheduled automations. Store cursors, "
            "watchlists, watermarks. Injected into the next run's prompt."
        ),
    )
