"""Shared tool: recall_skill — load a skill body on demand.

Skills are two-tier: `_index.md` is always in the prelude (tiny, one line
per skill); `<name>.md` is the full how-to body, loaded only when the model
decides to execute that skill. This tool is the on-demand half.

Registered once per agent (owner = that agent), so each agent recalls only
its own skills.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.agents.skills import SkillNameError, load_skill
from soveryn.platform.tools.registry import ToolSpec


def build_recall_skill_tool(
    *,
    skills_dir: Path | None = None,
    owner_agent: str,
) -> ToolSpec:
    """Return a `recall_skill` ToolSpec owned by `owner_agent`."""

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        skill_name = args.get("name", "")
        try:
            text = load_skill(owner_agent, skill_name, skills_dir=skills_dir)
        except SkillNameError as e:
            return {
                "ok": False,
                "error": "skill_name_invalid",
                "message": str(e),
            }
        if not text:
            return {
                "ok": False,
                "error": "skill_missing",
                "message": (
                    f"No skill named {skill_name!r} on disk for this agent. "
                    "Check the skills index in your prelude for available names."
                ),
            }
        return {
            "ok": True,
            "skill": skill_name,
            "content": text,
        }

    return ToolSpec(
        name="recall_skill",
        owner=owner_agent,
        description=(
            "Load the full body of one of your learned skills by name. "
            "Your prelude's skills index lists every skill you have; call "
            "this with a name from that index to get the step-by-step "
            "procedure before you act. Returns an error if the skill does "
            "not exist yet."
        ),
        schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Skill name exactly as it appears in your skills index "
                        "(lowercase, [a-z0-9_-])."
                    ),
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        handler=handler,
    )
