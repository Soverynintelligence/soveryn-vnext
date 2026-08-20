"""compose_post tool — Eve's draft-and-drop marketing surface.

Eve drafts Instagram/Facebook posts and drops them on Jon's Signal thread
for manual copy-paste to the real platforms. No Meta API, no credentials —
the human is the final gate.

Safety boundaries:
  - Image paths MUST be under data/media/ (no arbitrary file reads).
  - Caption is size-checked per platform (IG 2,200, FB 63,206).
  - Delivery is via signal_send (ungated) — Jon receives the draft.
  - Every call writes a marketing_log audit row.
"""
from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from soveryn.agents.signal_bridge.client import SignalCliError, send_once
from soveryn.agents.signal_bridge.config import SignalBridgeConfig
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec

# Platform constraints
PLATFORM_LIMITS: dict[str, int] = {
    "instagram": 2200,
    "facebook": 63206,
    "both": 2200,  # "both" means it must fit the tighter constraint
}

# Media root — compose_post may only reference images under this path
MEDIA_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "media"


def _validate_media_path(raw: str) -> str | None:
    """Validate that an image path is under data/media/ and is a real file.
    Returns an error string on failure, None on success."""
    if not isinstance(raw, str) or not raw.strip():
        return "image_path must be a non-empty string"
    p = Path(raw).resolve()
    # Must be under MEDIA_ROOT
    try:
        p.relative_to(MEDIA_ROOT.resolve())
    except ValueError:
        return (
            f"image_path must be under {MEDIA_ROOT} — "
            f"got {raw!r}. Place media in data/media/ first."
        )
    if not p.exists():
        return f"image does not exist: {raw}"
    if not p.is_file():
        return f"path is not a regular file: {raw}"
    # Basic image extension check
    if p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"):
        return f"not a recognized image file (got {p.suffix}): {raw}"
    return None


def _format_post(
    platform: str,
    content: str,
    image_path: str | None,
    audience: str | None,
) -> str:
    """Format a marketing post draft for Signal delivery."""
    lines: list[str] = []
    lines.append(f"=== MARKETING DRAFT ===")
    lines.append(f"Platform: {platform.upper()}")
    if audience:
        lines.append(f"Audience: {audience}")
    if image_path:
        # Use relative path from project root for readability
        try:
            rel = Path(image_path).resolve().relative_to(
                MEDIA_ROOT.resolve().parent.parent
            )
            lines.append(f"Image: {rel}")
        except ValueError:
            lines.append(f"Image: {image_path}")
    lines.append("")
    lines.append("--- CAPTION (copy-paste ready) ---")
    lines.append(content.strip())
    lines.append("---")
    lines.append("")

    # Platform-specific notes
    if platform in ("instagram", "both"):
        limit = PLATFORM_LIMITS["instagram"]
        used = len(content.strip())
        lines.append(f"Char count: {used}/{limit}")
        lines.append("Best time: 11am-1pm or 7-9pm local (audience-dependent)")
        if platform == "both":
            lines.append("FB note: Same caption works; FB allows up to 63,206 chars.")
    elif platform == "facebook":
        limit = PLATFORM_LIMITS["facebook"]
        used = len(content.strip())
        lines.append(f"Char count: {used}/{limit}")
        lines.append("Best time: 1-4pm local (FB peak)")

    lines.append("")
    lines.append("[Eve — Head of Marketing | SOVERYN]")
    return "\n".join(lines)


def build_compose_post_tool(
    *,
    config: SignalBridgeConfig,
    lattice_db_path: Path,
    owner_agent: str = "eve",
) -> ToolSpec:
    """Draft-and-drop marketing post tool. Formats a post and delivers
    it to Jon's Signal for manual publishing to IG/FB."""

    default_recipient: str | None = None
    if config.allowed_numbers:
        default_recipient = sorted(config.allowed_numbers)[0]

    def handler(args: Mapping[str, Any]) -> Any:
        platform = args.get("platform", "")
        if not isinstance(platform, str) or platform not in PLATFORM_LIMITS:
            raise ToolArgError(
                f"platform must be one of {list(PLATFORM_LIMITS.keys())}, "
                f"got {platform!r}"
            )

        content = args.get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise ToolArgError("content must be a non-empty string (the caption)")

        # Enforce platform char limit
        limit = PLATFORM_LIMITS[platform]
        if len(content.strip()) > limit:
            raise ToolArgError(
                f"content is {len(content.strip())} chars — exceeds "
                f"{platform} limit of {limit}. Trim and retry."
            )

        image_path = args.get("image_path")
        if image_path is not None:
            err = _validate_media_path(image_path)
            if err is not None:
                return {"error": "invalid_image", "message": err}

        audience = args.get("audience")
        if audience is not None and not isinstance(audience, str):
            raise ToolArgError("audience must be a string or null")

        # Format the post
        formatted = _format_post(
            platform=platform,
            content=content,
            image_path=image_path if image_path else None,
            audience=audience,
        )

        recipient = args.get("recipient") or default_recipient
        if not isinstance(recipient, str) or not recipient.strip():
            raise ToolArgError(
                "recipient must be a non-empty E.164 string, or default "
                "must be configured via SOVERYN_SIGNAL_ALLOWED_NUMBERS"
            )
        recipient = recipient.strip()
        if recipient not in config.allowed_numbers:
            raise ToolArgError(
                f"recipient {recipient!r} not in allowlist. "
                f"Allowed: {sorted(config.allowed_numbers)}."
            )

        # Deliver via signal-cli (same path as signal_send — ungated)
        try:
            send_once(
                signal_cli_bin=config.signal_cli_bin,
                bot_number=config.bot_number,
                recipient_e164=recipient,
                body=formatted,
                attachments=(),
            )
        except SignalCliError as e:
            _log_marketing_event(
                lattice_db_path,
                platform=platform,
                content_head=content[:200],
                image_path=image_path,
                error=f"signal delivery failed: {e}",
            )
            return {
                "error": "delivery_failed",
                "message": str(e),
                "recipient": recipient,
            }

        _log_marketing_event(
            lattice_db_path,
            platform=platform,
            content_head=content[:200],
            image_path=image_path,
            error=None,
        )

        return {
            "drafted": True,
            "platform": platform,
            "delivered_to": recipient,
            "delivered_at": datetime.now().isoformat(),
            "char_count": len(content.strip()),
            "char_limit": limit,
        }

    schema = {
        "type": "object",
        "properties": {
            "platform": {
                "type": "string",
                "enum": list(PLATFORM_LIMITS.keys()),
                "description": (
                    "Target platform: 'instagram' (2,200 char cap), "
                    "'facebook' (63,206 char cap), or 'both' (must fit "
                    "the tighter IG constraint)."
                ),
            },
            "content": {
                "type": "string",
                "description": (
                    "The full caption text, ready to copy-paste. Include "
                    "hashtags inline at the end. This is what Jon pastes "
                    "into the platform's post box."
                ),
            },
            "image_path": {
                "type": "string",
                "description": (
                    "Absolute path to the image file under data/media/. "
                    "Must be a real image file (.jpg, .png, .webp, etc). "
                    "Optional — omit for text-only posts."
                ),
            },
            "audience": {
                "type": "string",
                "description": (
                    "Optional target audience note (e.g. 'CWG homeowners', "
                    "'Soveryn community'). Helps Jon decide placement."
                ),
            },
            "recipient": {
                "type": "string",
                "description": (
                    "Optional E.164 Signal number. Defaults to Jon's number. "
                    "Must be in SOVERYN_SIGNAL_ALLOWED_NUMBERS."
                ),
            },
        },
        "required": ["platform", "content"],
        "additionalProperties": False,
    }
    return ToolSpec(
        name="compose_post",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Draft a marketing post for Instagram or Facebook and drop it "
            "on Jon's Signal for manual publishing. You write the caption, "
            "pick the image, note the audience — Jon copy-pastes it to the "
            "platform. No Meta API, no credentials. Use this for CWG, "
            "Soveryn, or ActTruth marketing content."
        ),
    )


def register_compose_post_tool(
    registry: ToolRegistry,
    *,
    config: SignalBridgeConfig,
    lattice_db_path: Path,
    owner_agent: str = "eve",
) -> None:
    """Register compose_post for one agent (Eve by default)."""
    registry.register(build_compose_post_tool(
        config=config,
        lattice_db_path=lattice_db_path,
        owner_agent=owner_agent,
    ))


def _log_marketing_event(
    lattice_db_path: Path,
    *,
    platform: str,
    content_head: str,
    image_path: str | None,
    error: str | None,
) -> None:
    """Write a marketing_log audit row. Failures are silent — the tool
    already returned a structured result to the model."""
    try:
        with sqlite3.connect(str(lattice_db_path)) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS marketing_log ("
                "  id TEXT PRIMARY KEY,"
                "  platform TEXT NOT NULL,"
                "  content_head TEXT,"
                "  image_path TEXT,"
                "  error TEXT,"
                "  created_at TEXT NOT NULL"
                ")"
            )
            con.execute(
                "INSERT INTO marketing_log "
                "(id, platform, content_head, image_path, error, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), platform, content_head, image_path,
                 error, datetime.now().isoformat()),
            )
    except Exception:
        pass
