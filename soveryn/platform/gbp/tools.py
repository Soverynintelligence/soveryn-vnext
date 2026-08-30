"""Eve tools: eve_gbp_status (read) + eve_gbp_post (Gate-only live CWG GBP)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.gbp.client import create_local_post, gbp_status
from soveryn.platform.gbp.config import CAPTION_LIMIT
from soveryn.platform.social.instagram_desk import list_inbox_images
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def build_eve_gbp_status_tool(*, owner_agent: str = "eve") -> ToolSpec:
    def handler(_args: Mapping[str, Any]) -> Any:
        return gbp_status()

    return ToolSpec(
        name="eve_gbp_status",
        owner=owner_agent,
        schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=handler,
        description=(
            "Read-only: is CWG Google Business Profile OAuth configured and "
            "authorized? Does not post. Does not spend ads."
        ),
    )


def build_eve_gbp_post_tool(
    *,
    owner_agent: str = "eve",
    post_fn=None,
) -> ToolSpec:
    poster = post_fn or create_local_post

    def handler(args: Mapping[str, Any]) -> Any:
        brand = args.get("brand", "cwg")
        if brand != "cwg":
            raise ToolArgError(
                "This desk is CWG Google Business only. Not SOVERYN, not ads."
            )
        caption = args.get("caption", "")
        if not isinstance(caption, str) or not caption.strip():
            raise ToolArgError("caption must be a non-empty string")
        image_path = args.get("image_path") or None
        if image_path is not None and not isinstance(image_path, str):
            raise ToolArgError("image_path must be a string if set")
        inbox = list_inbox_images()
        if image_path is not None and not image_path.strip():
            image_path = None
        if image_path:
            image_path = image_path.strip()
        result = poster(summary=caption.strip(), image_path=image_path)
        result["inbox"] = inbox
        return result

    return ToolSpec(
        name="eve_gbp_post",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "brand": {
                    "type": "string",
                    "enum": ["cwg"],
                    "description": "Must be cwg. Carolina Water Gardens listing only.",
                },
                "caption": {
                    "type": "string",
                    "description": (
                        f"GBP update, ≤ {CAPTION_LIMIT} chars. CWG voice. "
                        "No prices, no ads spend."
                    ),
                },
                "image_path": {
                    "type": "string",
                    "description": (
                        "Optional photo from Desktop/CWG-Instagram. "
                        "Text still posts if the photo cannot attach."
                    ),
                },
            },
            "required": ["brand", "caption"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Publish one Carolina Water Gardens Google Business Profile update "
            "(Maps / Search listing). brand must be cwg. Not ads, not billing. "
            "Messages Gate Allow required — never cadence. No credentials. "
            "If needs_login or needs_api_access, stop and tell Jon."
        ),
    )


def register_gbp_tools(registry: ToolRegistry, *, owner_agent: str = "eve") -> None:
    registry.register(build_eve_gbp_status_tool(owner_agent=owner_agent))
    registry.register(build_eve_gbp_post_tool(owner_agent=owner_agent))
