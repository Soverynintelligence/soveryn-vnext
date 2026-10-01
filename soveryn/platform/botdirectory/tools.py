"""Agent tools: browse + import botdirectory charters (Eve / Kernel)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.botdirectory.client import (
    BotDirectoryError,
    fetch_bot,
    search_bots,
)
from soveryn.platform.botdirectory.store import (
    get_import,
    import_charter,
    list_imports,
)
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def build_browse_bot_directory_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        q = args.get("q")
        category = args.get("category")
        integration = args.get("integration")
        limit = args.get("limit", 10)
        if q is not None and not isinstance(q, str):
            raise ToolArgError("q must be a string")
        if category is not None and not isinstance(category, str):
            raise ToolArgError("category must be a string")
        if integration is not None and not isinstance(integration, str):
            raise ToolArgError("integration must be a string")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ToolArgError("limit must be an integer")
        try:
            return search_bots(
                q=q, category=category, integration=integration, limit=limit,
            )
        except BotDirectoryError as e:
            return {"ok": False, "error": "botdirectory_failed", "message": str(e)}

    return ToolSpec(
        name="browse_bot_directory",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Search names, prompts, categories, integrations.",
                },
                "category": {
                    "type": "string",
                    "description": "Exact category filter (e.g. Marketing, Ops).",
                },
                "integration": {
                    "type": "string",
                    "description": "Exact integration filter (e.g. Slack, Instagram).",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "How many results (max 50).",
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Browse botdirectory.ai — public catalog of bot role charters "
            "(Grok Bot / Hermes Bot Mode genre). Returns summaries + prompt "
            "previews. Does NOT schedule anything. To keep a full charter "
            "locally for Jon's review, call import_bot_charter."
        ),
    )


def build_import_bot_charter_tool(
    *,
    owner_agent: str,
    data_root: Path | None = None,
) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        slug = args.get("slug")
        note = args.get("note")
        if not isinstance(slug, str) or not slug.strip():
            raise ToolArgError("slug must be a non-empty string")
        if note is not None and not isinstance(note, str):
            raise ToolArgError("note must be a string")
        try:
            bot = fetch_bot(slug.strip())
            imported = import_charter(bot, data_root=data_root, note=note)
        except BotDirectoryError as e:
            return {"ok": False, "error": "fetch_failed", "message": str(e)}
        except ValueError as e:
            raise ToolArgError(str(e)) from e
        return {
            "ok": True,
            "scheduled": False,
            "live": False,
            "import": {
                "slug": imported.slug,
                "name": imported.name,
                "category": imported.category,
                "path": imported.path,
                "imported_at": imported.imported_at,
                "detail_url": imported.detail_url,
                "prompt_chars": len(imported.prompt),
            },
            "message": (
                f"Saved {imported.name!r} under {imported.path}. "
                "Not scheduled. Not live. Jon promotes to Automations / "
                "Citizen duties only after review."
            ),
        }

    return ToolSpec(
        name="import_bot_charter",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "botdirectory slug (e.g. carousel-publisher).",
                },
                "note": {
                    "type": "string",
                    "description": "Optional note for Jon (why this charter).",
                },
            },
            "required": ["slug"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Import a full botdirectory charter to local disk for review "
            "(data/botdirectory/imports/<slug>.md). NEVER schedules, NEVER "
            "posts, NEVER enables live Automations. House rule: Jon decides "
            "promotion."
        ),
    )


def build_list_imported_bot_charters_tool(
    *,
    owner_agent: str,
    data_root: Path | None = None,
) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        limit = args.get("limit", 50)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ToolArgError("limit must be an integer")
        items = list_imports(data_root=data_root, limit=limit)
        return {
            "ok": True,
            "count": len(items),
            "imports": items,
            "scheduled": False,
            "note": "Local review copies only — none are live Automations.",
        }

    return ToolSpec(
        name="list_imported_bot_charters",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description="List botdirectory charters previously imported to local disk.",
    )


def build_get_imported_bot_charter_tool(
    *,
    owner_agent: str,
    data_root: Path | None = None,
) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        slug = args.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            raise ToolArgError("slug must be a non-empty string")
        try:
            return get_import(slug.strip(), data_root=data_root)
        except FileNotFoundError as e:
            return {"ok": False, "error": "not_imported", "message": str(e)}
        except ValueError as e:
            raise ToolArgError(str(e)) from e

    return ToolSpec(
        name="get_imported_bot_charter",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Slug of a previously imported charter (e.g. carousel-publisher).",
                },
            },
            "required": ["slug"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Read the full text of a locally imported botdirectory charter "
            "(including the complete prompt). Use this after import_bot_charter "
            "to give Jon a verdict. Does not schedule or post."
        ),
    )


def register_botdirectory_tools(
    registry: ToolRegistry,
    *,
    owner_agent: str = "eve",
    data_root: Path | None = None,
) -> None:
    """Register browse/import/list/get for one agent (Eve by default; Kernel too)."""
    registry.register(build_browse_bot_directory_tool(owner_agent=owner_agent))
    registry.register(
        build_import_bot_charter_tool(owner_agent=owner_agent, data_root=data_root)
    )
    registry.register(
        build_list_imported_bot_charters_tool(
            owner_agent=owner_agent, data_root=data_root
        )
    )
    registry.register(
        build_get_imported_bot_charter_tool(
            owner_agent=owner_agent, data_root=data_root
        )
    )
