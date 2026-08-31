"""Tool registration for house document intake."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.intake.pdf import extract_pdf_path
from soveryn.platform.intake.qr import decode_qr_bytes
from soveryn.platform.intake.turn_images import current_turn_images
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec
from soveryn.platform.vision_types import ALLOWED_IMAGE_MIME_PREFIXES

# Paths agents may read for intake (house-local only).
_DEFAULT_ALLOWED_ROOTS: tuple[Path, ...] = (
    Path.home() / "soveryn_vnext" / "data",
    Path.home() / "soveryn_citizens",
    Path.home() / "historys-ledger",
    Path.home() / "historysledger-site",
    Path.home() / "Downloads",
)


def _resolve_allowed(path: Path, allowed_roots: tuple[Path, ...]) -> Path:
    resolved = path.expanduser().resolve()
    for root in allowed_roots:
        try:
            root_r = root.expanduser().resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(root_r)
            return resolved
        except ValueError:
            continue
    raise ToolArgError(
        f"path {path} is outside allowed intake roots "
        f"(house data, citizens desks, History's Ledger, Downloads)"
    )


def build_intake_extract_pdf_tool(
    *,
    owner_agent: str,
    allowed_roots: tuple[Path, ...] | None = None,
) -> ToolSpec:
    roots = allowed_roots if allowed_roots is not None else _DEFAULT_ALLOWED_ROOTS

    def handler(args: Mapping[str, Any]) -> Any:
        raw = args.get("path", "")
        if not isinstance(raw, str) or not raw.strip():
            raise ToolArgError("path must be a non-empty string")
        resolved = _resolve_allowed(Path(raw.strip()), roots)
        if resolved.suffix.lower() != ".pdf":
            raise ToolArgError("intake_extract_pdf only accepts .pdf files in v0")
        result = extract_pdf_path(resolved)
        return result.as_dict()

    return ToolSpec(
        name="intake_extract_pdf",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to a PDF on the house disk "
                        "(data/, citizens desks, History's Ledger, or Downloads). "
                        "Returns extracted text + page map. status=failed|partial "
                        "with an explicit gap when there is no text layer — "
                        "never invent page content."
                    ),
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Extract text from a held PDF (text layer only in v0). "
            "Use when Jon attaches or points at a PDF. If status is failed "
            "(scan/encrypted/empty), report the gap — do not invent quotations."
        ),
    )


def register_intake_tools(
    registry: ToolRegistry,
    *,
    owner_agent: str,
    allowed_roots: tuple[Path, ...] | None = None,
) -> None:
    """Register intake tools for one agent."""
    registry.register(
        build_intake_extract_pdf_tool(
            owner_agent=owner_agent,
            allowed_roots=allowed_roots,
        )
    )


_CURRENT_IMAGE = "current"


def _decode_data_url(url: str) -> bytes:
    if not url.startswith(ALLOWED_IMAGE_MIME_PREFIXES):
        raise ToolArgError(
            "image must be \"current\" or a data:image/{jpeg,png,webp,gif} URL"
        )
    comma = url.find(",")
    if comma < 0:
        raise ToolArgError("image data URL is missing payload")
    try:
        return base64.b64decode(url[comma + 1 :], validate=False)
    except Exception as exc:  # noqa: BLE001 — surface as a tool miss, not a crash
        raise ToolArgError(f"image data URL is not valid base64: {exc}") from exc


def _miss(*, miss: str) -> dict[str, Any]:
    return {
        "ok": False,
        "payloads": [],
        "symbology": None,
        "miss": miss,
    }


def _decode_urls(urls: tuple[str, ...]) -> dict[str, Any]:
    """Decode every in-flight / supplied data URL. Never invent a payload."""
    if not urls:
        return _miss(miss="no_in_flight_image")
    payloads: list[str] = []
    saw_unreadable = False
    saw_locator = False
    for url in urls:
        result = decode_qr_bytes(_decode_data_url(url))
        payloads.extend(result.payloads)
        if result.miss == "unreadable":
            saw_unreadable = True
        if result.symbology == "QR" or result.ok:
            saw_locator = True
    if payloads:
        return {
            "ok": True,
            "payloads": payloads,
            "symbology": "QR",
            "miss": None,
        }
    if saw_unreadable or saw_locator:
        return _miss(miss="unreadable")
    return _miss(miss="no_code_found")


def build_decode_qr_tool(
    *,
    owner_agent: str,
    allowed_roots: tuple[Path, ...] | None = None,
) -> ToolSpec:
    """QR-decode desk tool. Path on disk, data URL, or this turn's photo."""
    roots = allowed_roots if allowed_roots is not None else _DEFAULT_ALLOWED_ROOTS

    def handler(args: Mapping[str, Any]) -> Any:
        raw_path = args.get("path", "")
        raw_image = args.get("image", "")
        path_s = raw_path.strip() if isinstance(raw_path, str) else ""
        image_s = raw_image.strip() if isinstance(raw_image, str) else ""

        if raw_path is not None and not isinstance(raw_path, str):
            raise ToolArgError("path must be a string")
        if raw_image is not None and not isinstance(raw_image, str):
            raise ToolArgError("image must be a string")

        if path_s:
            resolved = _resolve_allowed(Path(path_s), roots)
            if not resolved.is_file():
                raise ToolArgError(f"path {path_s} is not a regular file")
            return decode_qr_bytes(resolved.read_bytes()).as_dict()

        if image_s and image_s.lower() != _CURRENT_IMAGE:
            return _decode_urls((image_s,))

        # image="current" or both omitted — this turn's in-flight attachments.
        return _decode_urls(current_turn_images())

    return ToolSpec(
        name="decode_qr",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to an image on the house disk "
                        "(data/, citizens desks, History's Ledger, or Downloads)."
                    ),
                },
                "image": {
                    "type": "string",
                    "description": (
                        "Pass \"current\" to decode the photo Jon just sent "
                        "on this Messages turn (in-flight; not saved to the DB). "
                        "Or a data:image/{jpeg,png,webp,gif} URL. "
                        "Never guess a QR payload from pixels — call this tool."
                    ),
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Decode a QR code from a photo Jon just sent (image=\"current\") "
            "or from a house-disk path. Returns ok, payloads, symbology, and "
            "an explicit miss (no_code_found / unreadable / no_in_flight_image). "
            "Never invent a URL."
        ),
    )


def register_qr_tools(
    registry: ToolRegistry,
    *,
    owner_agent: str,
    allowed_roots: tuple[Path, ...] | None = None,
) -> None:
    """Register decode_qr for one agent. Default owner is Eve (Messages)."""
    registry.register(
        build_decode_qr_tool(
            owner_agent=owner_agent,
            allowed_roots=allowed_roots,
        )
    )
