"""Eve tools for Canva create / autofill / export."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.canva import client as canva_client
from soveryn.platform.canva.config import load_config
from soveryn.platform.canva.oauth import CanvaAuthError
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def _not_ready(exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "canva_not_ready",
        "message": str(exc),
        "hint": (
            "Set SOVERYN_CANVA_CLIENT_ID / SOVERYN_CANVA_CLIENT_SECRET, then "
            "run: python -m soveryn.platform.canva authorize"
        ),
    }


def build_canva_status_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        cfg = load_config()
        return {
            "ok": True,
            "configured": cfg.configured,
            "authorized": cfg.authorized,
            "brand_templates": dict(cfg.brand_templates),
            "media_dir": str(cfg.media_dir),
            "redirect_uri": cfg.redirect_uri,
        }

    return ToolSpec(
        name="canva_status",
        owner=owner_agent,
        description=(
            "Check whether Canva Connect is configured and authorized for the "
            "house. Use before create/export if unsure."
        ),
        schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
    )


def build_canva_list_templates_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        q = args.get("query")
        if q is not None and not isinstance(q, str):
            raise ToolArgError("query must be a string")
        limit = args.get("limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ToolArgError("limit must be an integer")
        cfg = load_config()
        # Prefer configured map when no query
        if not q and cfg.brand_templates:
            return {
                "ok": True,
                "source": "env",
                "templates": [
                    {"brand": b, "brand_template_id": tid}
                    for b, tid in cfg.brand_templates.items()
                ],
            }
        try:
            raw = canva_client.list_brand_templates(
                query=q, limit=limit, config=cfg
            )
            items = raw.get("items") or raw.get("brand_templates") or []
            return {"ok": True, "source": "api", "templates": items, "raw_keys": list(raw)}
        except (CanvaAuthError, canva_client.CanvaAPIError) as e:
            return _not_ready(e)

    return ToolSpec(
        name="canva_list_templates",
        owner=owner_agent,
        description=(
            "List Canva brand templates (or the house env map "
            "SOVERYN_CANVA_TEMPLATES). Use to pick a template id before "
            "canva_autofill_post."
        ),
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_canva_create_design_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        title = args.get("title") or "SOVERYN post"
        if not isinstance(title, str):
            raise ToolArgError("title must be a string")
        width = int(args.get("width") or 1080)
        height = int(args.get("height") or 1080)
        image_path = args.get("image_path")
        if image_path is not None and not isinstance(image_path, str):
            raise ToolArgError("image_path must be a string")
        try:
            if image_path:
                result = canva_client.make_design_from_image(
                    image_path,
                    title=title,
                    width=width,
                    height=height,
                )
                result["note"] = (
                    "Design created WITH your image (not blank). Next: "
                    "canva_export_design, then compose_post with the PNG."
                )
                return result
            raw = canva_client.create_ig_design(
                title=title, width=width, height=height
            )
            design = raw.get("design") or raw
            return {
                "ok": True,
                "design_id": design.get("id"),
                "edit_url": design.get("urls", {}).get("edit_url")
                or design.get("url"),
                "title": design.get("title"),
                "blank": True,
                "note": (
                    "BLANK canvas — do not use for finished posts. Pass "
                    "image_path (under data/media/) or use canva_autofill_post "
                    "with a brand template."
                ),
                "raw": design,
            }
        except (CanvaAuthError, canva_client.CanvaAPIError) as e:
            return _not_ready(e)

    return ToolSpec(
        name="canva_create_design",
        owner=owner_agent,
        description=(
            "Create an IG Canva design. ALWAYS pass image_path under "
            "data/media/ (pond photo, generated graphic) — blank canvases are "
            "useless for posting. Prefer canva_autofill_post when brand "
            "templates are configured."
        ),
        schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "image_path": {
                    "type": "string",
                    "description": (
                        "Absolute path under data/media/ — uploaded into the "
                        "design so it is not empty."
                    ),
                },
                "width": {"type": "integer", "minimum": 40, "maximum": 8000},
                "height": {"type": "integer", "minimum": 40, "maximum": 8000},
            },
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_canva_autofill_post_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        brand = str(args.get("brand") or "").strip().lower()
        template_id = str(args.get("brand_template_id") or "").strip()
        hook = str(args.get("hook") or "").strip()
        body = str(args.get("body") or "").strip()
        hashtags = str(args.get("hashtags") or "").strip()
        title = str(args.get("title") or "").strip() or None
        cfg = load_config()
        if not template_id and brand:
            template_id = cfg.brand_templates.get(brand, "")
        if not template_id:
            raise ToolArgError(
                "brand_template_id required (or brand matching "
                "SOVERYN_CANVA_TEMPLATES)"
            )
        if not hook and not body:
            raise ToolArgError("hook or body required")
        # Common field names — Brand Templates should use these (or map later).
        fields: dict[str, str] = {}
        if hook:
            fields["HOOK"] = hook
        if body:
            fields["BODY"] = body
        if hashtags:
            fields["HASHTAGS"] = hashtags
        # Also fill lowercase aliases some templates use
        extra = {}
        for k, v in list(fields.items()):
            extra[k.lower()] = v
        fields.update(extra)
        try:
            result = canva_client.autofill_and_wait(
                brand_template_id=template_id,
                fields=fields,
                title=title or hook[:80] or "SOVERYN post",
                config=cfg,
            )
            result["brand"] = brand or None
            result["schedule_hint"] = (
                "Open edit_url in Canva → Share/Schedule (Pro Content Planner) "
                "to post to IG/FB. Do NOT claim posted until Jon schedules."
            )
            return result
        except (CanvaAuthError, canva_client.CanvaAPIError) as e:
            return _not_ready(e)

    return ToolSpec(
        name="canva_autofill_post",
        owner=owner_agent,
        description=(
            "Create a Canva design from a brand template by filling HOOK/BODY/"
            "HASHTAGS. Returns design_id + edit_url. Then call "
            "canva_export_design and compose_post with the PNG path. Publishing "
            "to Instagram is Jon→Canva Content Planner (or manual), not this tool."
        ),
        schema={
            "type": "object",
            "properties": {
                "brand": {
                    "type": "string",
                    "enum": ["hl", "soveryn", "cwg", "acttruth"],
                    "description": "Maps to SOVERYN_CANVA_TEMPLATES if set.",
                },
                "brand_template_id": {"type": "string"},
                "hook": {"type": "string"},
                "body": {"type": "string"},
                "hashtags": {"type": "string"},
                "title": {"type": "string"},
            },
            "additionalProperties": False,
        },
        handler=handler,
    )


def build_canva_export_design_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        design_id = str(args.get("design_id") or "").strip()
        if not design_id:
            raise ToolArgError("design_id required")
        fmt = str(args.get("format") or "png").strip().lower()
        if fmt not in ("png", "jpg", "mp4"):
            raise ToolArgError("format must be png, jpg, or mp4")
        try:
            return canva_client.export_design_to_media(
                design_id, format_type=fmt
            )
        except (CanvaAuthError, canva_client.CanvaAPIError) as e:
            return _not_ready(e)

    return ToolSpec(
        name="canva_export_design",
        owner=owner_agent,
        description=(
            "Export a Canva design to data/media/canva/ (PNG by default). Pass "
            "the returned path to compose_post as image_path."
        ),
        schema={
            "type": "object",
            "properties": {
                "design_id": {"type": "string"},
                "format": {
                    "type": "string",
                    "enum": ["png", "jpg", "mp4"],
                },
            },
            "required": ["design_id"],
            "additionalProperties": False,
        },
        handler=handler,
    )


def register_canva_tools(
    registry: ToolRegistry,
    *,
    owner_agent: str = "eve",
) -> None:
    registry.register(build_canva_status_tool(owner_agent=owner_agent))
    registry.register(build_canva_list_templates_tool(owner_agent=owner_agent))
    registry.register(build_canva_create_design_tool(owner_agent=owner_agent))
    registry.register(build_canva_autofill_post_tool(owner_agent=owner_agent))
    registry.register(build_canva_export_design_tool(owner_agent=owner_agent))
