"""kernel_child — list / steer / stop live Aider and OpenCode kids."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.kernel_jobs import get_store
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


def build_kernel_child_tool(*, owner_agent: str = "kernel") -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        action = (args.get("action") or "").strip().lower()
        if action not in {"list", "stop", "steer"}:
            raise ToolArgError("action must be list, stop, or steer")
        store = get_store()
        if action == "list":
            running_only = bool(args.get("running_only", True))
            jobs = store.list_jobs(running_only=running_only)
            return {"ok": True, "jobs": jobs, "count": len(jobs)}
        job_id = args.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise ToolArgError("job_id is required for stop/steer")
        job_id = job_id.strip()
        if action == "stop":
            return store.stop(job_id)
        message = args.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ToolArgError("steer needs message")

        def spawn_job(*, kind, prompt, repo, follow_of):
            from pathlib import Path

            from soveryn.platform.aider_tool import find_aider, run_aider
            from soveryn.platform.kernel_jobs import ChildJob
            from soveryn.platform.opencode_tool import (
                _timeout_s,
                find_launcher,
                run_opencode,
            )

            cwd = Path(repo)
            if kind == "opencode":
                launcher = find_launcher()
                if not launcher:
                    raise ToolArgError("soveryn-opencode not found")
                raw = run_opencode(
                    prompt,
                    repo=cwd,
                    launcher=launcher,
                    timeout_s=_timeout_s(),
                    wait=False,
                    follow_of=follow_of,
                    store=store,
                )
            else:
                launcher = find_aider()
                if not launcher:
                    raise ToolArgError("soveryn-aider not found")
                raw = run_aider(
                    prompt,
                    repo=cwd,
                    launcher=launcher,
                    timeout_s=_timeout_s(),
                    wait=False,
                    follow_of=follow_of,
                    store=store,
                )
            job = raw.get("job") if isinstance(raw, dict) else raw
            if not isinstance(job, ChildJob):
                raise ToolArgError("follow-up spawn did not register a job")
            return job

        return store.steer(job_id, message.strip(), spawn_fn=spawn_job)

    return ToolSpec(
        name="kernel_child",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "stop", "steer"],
                    "description": (
                        "list running Kernel Aider/OpenCode kids; stop one "
                        "(keeps partial tree); steer = stop + respawn with a correction."
                    ),
                },
                "job_id": {"type": "string", "description": "Required for stop/steer."},
                "message": {
                    "type": "string",
                    "description": "Steer text. Keep existing diffs; also do this.",
                },
                "running_only": {
                    "type": "boolean",
                    "description": "list: default true.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "List, stop, or steer Kernel's live Aider/OpenCode children. "
            "Stop keeps the partial working tree. Steer interrupts and "
            "respawns with the correction. Does not spawn a new mend — use "
            "run_aider / run_opencode for that."
        ),
    )
