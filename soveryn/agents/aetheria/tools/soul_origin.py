"""Aetheria tool: load the origin essay off the hot path (Memory Grades PR5)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.agents.souls import get_soul_origin
from soveryn.platform.tools.registry import ToolSpec


def build_read_soul_origin_tool(
    *,
    souls_dir: Path | None = None,
    owner_agent: str = "aetheria",
) -> ToolSpec:
    """Return origin essay text for Aetheria (HOW WE BECAME SOVERYN).

    Soul hard rules stay in the always-on prelude; the origin essay is loaded
    only when she asks. Same PR as origin-off (design invariant 3).
    """

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        text = get_soul_origin(
            owner_agent, souls_dir=souls_dir, raise_on_missing=False,
        )
        if not text:
            return {
                "ok": False,
                "error": "soul_origin_missing",
                "message": "No origin essay on disk for this agent.",
            }
        return {
            "ok": True,
            "title": "HOW WE BECAME SOVERYN",
            "content": text,
        }

    return ToolSpec(
        name="read_soul_origin",
        owner=owner_agent,
        description=(
            "Read Aetheria's origin essay (HOW WE BECAME SOVERYN) — the story of "
            "how SOVERYN and the Lattice began. Not on the hot path; call only "
            "when you need that narrative. Hard rules of who you are are already "
            "in your soul prelude without this tool."
        ),
        schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=handler,
    )
