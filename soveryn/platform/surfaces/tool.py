"""`fleet_status` — let an agent ask what is supposed to be running, and what is.

The rule this exists to satisfy is Jon's, and it is the one every incident this
week violated: **every write path an agent can take needs a corresponding read
path back to that agent.** Seven instances of that defect surfaced in a single
week, each fixed by adding a read path rather than by changing a prompt.

Aetheria could restart nothing, diagnose nothing and confirm nothing about the
fleet she lives in, because no tool answered "what should be up?" She could be
told the answer by Jon. She could not look.

The output is shaped so that an agent reading it quickly cannot mistake unknown
for healthy — `unknown` is its own list, with its own note, and the summary
sentence names it. That shape is deliberate. The earlier `spark_status` tool led
with an empty container list and Vett correctly concluded the machine was idle
while vLLM was serving her every token. How a probe result is *presented*
decides what gets believed.

Read-only. It answers "what is true right now"; it starts and stops nothing.
"""
from __future__ import annotations

from typing import Any, Mapping

from soveryn.platform.surfaces import registry
from soveryn.platform.surfaces.probe import Status, probe_all
from soveryn.platform.surfaces.staleness import Observations
from soveryn.platform.tools.registry import ToolSpec


def build_fleet_status_tool(*, owner_agent: str, timeout: float = 20.0) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        only_mine = bool(args.get("only_mine"))
        surfaces = (registry.owned_by(owner_agent) if only_mine else registry.live())
        if not surfaces:
            return {"ok": False,
                    "error": f"no surfaces declared for owner={owner_agent!r}",
                    "note": "This is a registry gap, NOT an all-clear."}

        results = probe_all(surfaces, timeout=timeout)
        obs = Observations()
        obs.record(results)

        healthy = [r.surface for r in results if r.status is Status.HEALTHY]
        down = [{"surface": r.surface, "detail": r.detail}
                for r in results if r.status is Status.FAILED]
        unknown = [{"surface": r.surface, "detail": r.detail}
                   for r in results if r.status is Status.UNKNOWN]
        never = [s.surface for s in obs.stale(surfaces) if s.never]

        # Lead with the load-bearing sentence, and never let "no failures" be
        # read as "all good" while anything is unknown.
        if down:
            summary = (f"{len(down)} declared surface(s) are DOWN: "
                       + ", ".join(d["surface"] for d in down) + ".")
        elif unknown:
            summary = (f"No confirmed failures, but {len(unknown)} surface(s) could "
                       "NOT be checked — their state is unknown, not healthy.")
        else:
            summary = f"All {len(healthy)} declared surfaces verified working."

        return {
            "ok": True,
            "summary": summary,
            "down": down,
            "unknown": unknown,
            "never_verified": never,
            "healthy": healthy,
            "declared_total": len(surfaces),
            "note": ("'unknown' means the probe could not run. It is NOT evidence "
                     "the surface is fine. A surface missing from this list "
                     "entirely is undeclared and therefore unwatched."),
        }

    return ToolSpec(
        name="fleet_status",
        owner=owner_agent,
        description=(
            "Check every surface SOVERYN declares it is running — public sites, "
            "agent endpoints, routers, daemons — by making a real request to "
            "each, not by reading a status flag. Returns down / unknown / "
            "healthy separately. 'unknown' means the check could not run and "
            "must never be treated as healthy. Read-only."
        ),
        schema={"type": "object",
                "properties": {"only_mine": {
                    "type": "boolean",
                    "description": "Only surfaces owned by this agent."}},
                "required": []},
        handler=handler,
    )


def register_fleet_status_tool(registry_obj, *, owner_agent: str) -> None:
    registry_obj.register(build_fleet_status_tool(owner_agent=owner_agent))
