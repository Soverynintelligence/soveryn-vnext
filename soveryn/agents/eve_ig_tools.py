"""eve_ig_post — live CWG Instagram via the bounded desk.

Always Gate-approved. Never cadence. No password. Session or needs_login.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.social.instagram_desk import InstagramDesk, default_desk
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def build_eve_ig_post_tool(
    *,
    owner_agent: str = "eve",
    desk: InstagramDesk | None = None,
) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        brand = args.get("brand", "cwg")
        if brand != "cwg":
            raise ToolArgError(
                "This desk is CWG Instagram only. Use compose_post → Signal "
                "for SOVERYN or ActTruth drafts."
            )
        caption = args.get("caption", "")
        if not isinstance(caption, str) or not caption.strip():
            raise ToolArgError("caption must be a non-empty string")
        image_path = args.get("image_path", "")
        d = desk or default_desk(headed=False)
        from soveryn.platform.social.instagram_desk import list_inbox_images
        inbox = list_inbox_images(getattr(d, "inbox", None))
        if not isinstance(image_path, str) or not image_path.strip():
            return {
                "ok": False,
                "status": "need_image",
                "inbox": inbox,
                "thread_note": (
                    "Drop a photo in Desktop/CWG-Instagram and pass that path "
                    "as image_path. Live post still needs Messages Allow."
                    if inbox
                    else "Desktop/CWG-Instagram is empty. Jon drops photos there."
                ),
            }
        result = d.publish(image_path=image_path.strip(), caption=caption.strip())
        result["inbox"] = inbox
        if result.get("status") == "needs_login":
            result["thread_note"] = (
                "IG desk is logged out. Jon runs "
                "`python -m soveryn.platform.social.instagram_desk login` "
                "then Allow again. I do not type credentials."
            )
        elif result.get("ok"):
            result["thread_note"] = "Posted to CWG Instagram from the desk."
        else:
            result.setdefault(
                "thread_note",
                result.get("message") or "Instagram desk did not post.",
            )
        return result

    return ToolSpec(
        name="eve_ig_post",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "brand": {
                    "type": "string",
                    "enum": ["cwg"],
                    "description": "Must be cwg. This desk is Carolina Water Gardens Instagram only.",
                },
                "caption": {
                    "type": "string",
                    "description": (
                        "Instagram caption, ≤ 2,200 chars, hashtags at the end. "
                        "CWG voice only for this desk."
                    ),
                },
                "image_path": {
                    "type": "string",
                    "description": (
                        "Photo from Desktop/CWG-Instagram (preferred) or data/media/. "
                        "jpg/png/webp."
                    ),
                },
            },
            "required": ["brand", "caption"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Publish one Carolina Water Gardens Instagram post from Eve's "
            "dedicated browser desk. brand must be cwg. Not Facebook, not "
            "SOVERYN, not ActTruth. Jon must already be logged in on the CWG "
            "IG account. Messages Gate Allow required — never cadence. "
            "If needs_login, stop. No credentials. "
            "Photos: Jon drops files in Desktop/CWG-Instagram. "
            "Live post only after Messages Allow — never cadence."
        ),
    )


def register_eve_ig_post_tool(
    registry: ToolRegistry,
    *,
    owner_agent: str = "eve",
    desk: InstagramDesk | None = None,
) -> None:
    registry.register(
        build_eve_ig_post_tool(owner_agent=owner_agent, desk=desk)
    )
