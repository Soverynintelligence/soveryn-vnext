"""Eve tools for her Google browser desk (Business + Ads session)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.social.agent_desk import desk_status
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec


def build_eve_google_desk_status_tool(*, owner_agent: str = "eve") -> ToolSpec:
    def handler(_args: Mapping[str, Any]) -> Any:
        info = desk_status("eve", "google")
        info["spend"] = False
        info["note"] = (
            "This is Eve's signed-in Google desk (Business + Ads). "
            "She does not create campaigns or change budget from this tool. "
            "Jon signs in with: python -m soveryn.platform.social.agent_desk "
            "login eve google"
        )
        return info

    return ToolSpec(
        name="eve_google_desk_status",
        owner=owner_agent,
        schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
        description=(
            "Is Eve's CWG Google desk signed in (Business + Ads)? Read-only. "
            "Does not spend. If needs_login, tell Jon to run "
            "`python -m soveryn.platform.social.agent_desk login eve google`."
        ),
    )


def register_google_desk_tools(registry: ToolRegistry, *, owner_agent: str = "eve") -> None:
    registry.register(build_eve_google_desk_status_tool(owner_agent=owner_agent))
