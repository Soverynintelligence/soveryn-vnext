"""Tool registration for house document intake."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.intake.compose import compose_overlay
from soveryn.platform.intake.draw import (
    draw_rectangle,
    draw_text_on_image,
    make_solid_canvas,
    parse_hex_color,
)
from soveryn.platform.intake.pdf import extract_pdf_path
from soveryn.platform.intake.qr import decode_qr_bytes, encode_qr_png
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


# Match soveryn.platform.web.fetch.ALLOWED_SCHEMES. make_qr encodes only —
# it must never fetch the URL. SSRF does not apply to encode-only.
_QR_URL_SCHEMES = frozenset({"http", "https"})


def _default_media_root() -> Path:
    try:
        from soveryn.config.loader import DEFAULT_DATA_ROOT

        return Path(DEFAULT_DATA_ROOT) / "media"
    except Exception:
        return Path.home() / "soveryn_vnext" / "data" / "media"


def _require_http_url(raw: Any) -> str:
    """House URL rule (fetch scheme whitelist) without fetching."""
    if not isinstance(raw, str) or not raw.strip():
        raise ToolArgError("url must be a non-empty http(s) URL")
    url = raw.strip()
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in _QR_URL_SCHEMES:
        raise ToolArgError(
            f"scheme {parsed.scheme!r} not allowed (only http/https)"
        )
    if not parsed.hostname:
        raise ToolArgError("url has no hostname")
    return url


def _as_int(name: str, raw: Any, *, required: bool = True) -> int | None:
    if raw is None:
        if required:
            raise ToolArgError(f"{name} is required")
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ToolArgError(f"{name} must be an integer")
    if int(raw) != raw:
        raise ToolArgError(f"{name} must be an integer")
    return int(raw)


def _safe_stem(raw: str, *, fallback: str) -> str:
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-._")
    return (cleaned[:48] or fallback)


def _alloc_png_path(media_root: Path, subdir: str, stem: str) -> Path:
    import uuid

    dest_dir = media_root.expanduser().resolve() / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    return (dest_dir / f"{stem}_{uuid.uuid4().hex[:8]}.png").resolve()


def _write_png(media_root: Path, subdir: str, stem: str, data: bytes) -> Path:
    dest = _alloc_png_path(media_root, subdir, stem)
    dest.write_bytes(data)
    return dest


def build_make_qr_tool(
    *,
    owner_agent: str,
    media_root: Path | None = None,
) -> ToolSpec:
    """URL → scannable PNG under data/media/qr/. Encodes only — never fetches."""
    root = media_root if media_root is not None else _default_media_root()

    def handler(args: Mapping[str, Any]) -> Any:
        url = _require_http_url(args.get("url"))
        from urllib.parse import urlparse

        stem = _safe_stem(urlparse(url).hostname or "qr", fallback="qr")
        try:
            png = encode_qr_png(url)
        except Exception as exc:  # noqa: BLE001 — miss, don't crash the loop
            return {
                "ok": False,
                "path": None,
                "url": url,
                "miss": "encode_failed",
                "message": str(exc),
            }
        dest = _write_png(root, "qr", stem, png)
        return {
            "ok": True,
            "path": str(dest),
            "url": url,
            "miss": None,
        }

    return ToolSpec(
        name="make_qr",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "http(s) URL to encode. The tool writes a scannable PNG "
                        "under data/media/qr/ and returns the absolute path. "
                        "It does not fetch the URL."
                    ),
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Encode an http(s) URL as a scannable QR PNG under data/media/qr/. "
            "Use this instead of HTML with a placeholder src. Returns the "
            "absolute path. Does not fetch the URL."
        ),
    )


def build_compose_image_tool(
    *,
    owner_agent: str,
    allowed_roots: tuple[Path, ...] | None = None,
    media_root: Path | None = None,
) -> ToolSpec:
    """Paste an overlay onto a base/template PNG at (x, y)."""
    roots = allowed_roots if allowed_roots is not None else _DEFAULT_ALLOWED_ROOTS
    out_root = media_root if media_root is not None else _default_media_root()

    def handler(args: Mapping[str, Any]) -> Any:
        raw_base = args.get("base") or args.get("template") or ""
        raw_overlay = args.get("overlay") or ""
        if not isinstance(raw_base, str) or not raw_base.strip():
            raise ToolArgError("base must be a non-empty path")
        if not isinstance(raw_overlay, str) or not raw_overlay.strip():
            raise ToolArgError("overlay must be a non-empty path")
        x = _as_int("x", args.get("x"))
        y = _as_int("y", args.get("y"))
        if x is None or y is None:
            raise ToolArgError("x and y are required")
        width = _as_int("width", args.get("width"), required=False)
        height = _as_int("height", args.get("height"), required=False)
        clip = args.get("clip", False)
        if clip is not None and not isinstance(clip, bool):
            raise ToolArgError("clip must be a boolean")

        base = _resolve_allowed(Path(raw_base.strip()), roots)
        overlay = _resolve_allowed(Path(raw_overlay.strip()), roots)
        dest = _alloc_png_path(out_root, "composed", "card")
        result = compose_overlay(
            base,
            overlay,
            x=int(x),
            y=int(y),
            width=width,
            height=height,
            clip=bool(clip),
            dest=dest,
        )
        return result.as_dict()

    return ToolSpec(
        name="compose_image",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "base": {
                    "type": "string",
                    "description": (
                        "Absolute path to the template / base PNG (data/media, "
                        "citizens desks, History's Ledger, or Downloads)."
                    ),
                },
                "overlay": {
                    "type": "string",
                    "description": "Absolute path to the overlay image (QR, photo).",
                },
                "x": {
                    "type": "integer",
                    "description": "Left pixel of the overlay on the base.",
                },
                "y": {
                    "type": "integer",
                    "description": "Top pixel of the overlay on the base.",
                },
                "width": {
                    "type": "integer",
                    "description": "Optional overlay width in pixels (keeps file aspect if omitted with height).",
                },
                "height": {
                    "type": "integer",
                    "description": "Optional overlay height in pixels.",
                },
                "clip": {
                    "type": "boolean",
                    "description": (
                        "If false (default), refuse when the overlay would "
                        "extend past the base (miss=would_clip). If true, "
                        "PIL clips the overlay to the base."
                    ),
                },
            },
            "required": ["base", "overlay", "x", "y"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Local compositor: drop an overlay (QR, photo) onto a template at "
            "x,y and export a PNG under data/media/composed/. Not Canva. "
            "Returns the absolute path. miss=file_not_found / would_clip "
            "unless clip=true."
        ),
    )


_CANVAS_EDGE_MIN = 1
_CANVAS_EDGE_MAX = 4096
_FONT_KINDS = frozenset({"serif", "sans", "serif_italic"})
_ALIGN_KINDS = frozenset({"left", "center", "right"})


def _hex_color(name: str, raw: Any) -> tuple[int, int, int]:
    if not isinstance(raw, str):
        raise ToolArgError(f"{name} must be a #RGB or #RRGGBB hex color")
    try:
        return parse_hex_color(raw)
    except ValueError:
        raise ToolArgError(f"{name} must be a #RGB or #RRGGBB hex color") from None


def _optional_hex(name: str, raw: Any) -> tuple[int, int, int] | None:
    if raw is None or raw == "":
        return None
    return _hex_color(name, raw)


def _canvas_edge(name: str, raw: Any) -> int:
    value = _as_int(name, raw)
    if value is None or value < _CANVAS_EDGE_MIN or value > _CANVAS_EDGE_MAX:
        raise ToolArgError(
            f"{name} must be an integer from {_CANVAS_EDGE_MIN} to {_CANVAS_EDGE_MAX}"
        )
    return value


def _positive_int(name: str, raw: Any) -> int:
    value = _as_int(name, raw)
    if value is None or value < 1:
        raise ToolArgError(f"{name} must be a positive integer")
    return value


def build_make_canvas_tool(
    *,
    owner_agent: str,
    media_root: Path | None = None,
) -> ToolSpec:
    """Solid RGB PNG under data/media/canvas/. Hex fill is an argument."""
    out_root = media_root if media_root is not None else _default_media_root()

    def handler(args: Mapping[str, Any]) -> Any:
        width = _canvas_edge("width", args.get("width"))
        height = _canvas_edge("height", args.get("height"))
        fill = _hex_color("fill", args.get("fill"))
        raw_name = args.get("name")
        if raw_name is None or raw_name == "":
            stem = "canvas"
        elif isinstance(raw_name, str):
            stem = _safe_stem(raw_name, fallback="canvas")
        else:
            raise ToolArgError("name must be a string")
        dest = _alloc_png_path(out_root, "canvas", stem)
        return make_solid_canvas(dest, width=width, height=height, fill=fill).as_dict()

    return ToolSpec(
        name="make_canvas",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "width": {
                    "type": "integer",
                    "description": "Canvas width in pixels (1..4096).",
                },
                "height": {
                    "type": "integer",
                    "description": "Canvas height in pixels (1..4096).",
                },
                "fill": {
                    "type": "string",
                    "description": (
                        "Solid fill as #RGB or #RRGGBB (e.g. \"#071A2C\"). "
                        "Not a color name."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Optional filename stem under data/media/canvas/.",
                },
            },
            "required": ["width", "height", "fill"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Create a solid RGB PNG under data/media/canvas/. Use this for a "
            "branded field instead of SVG/HTML. Returns ok, path, width, height."
        ),
    )


def build_draw_rect_tool(
    *,
    owner_agent: str,
    allowed_roots: tuple[Path, ...] | None = None,
    media_root: Path | None = None,
) -> ToolSpec:
    """Draw a rectangle onto an existing PNG; write a new composed PNG."""
    roots = allowed_roots if allowed_roots is not None else _DEFAULT_ALLOWED_ROOTS
    out_root = media_root if media_root is not None else _default_media_root()

    def handler(args: Mapping[str, Any]) -> Any:
        raw_path = args.get("path", "")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ToolArgError("path must be a non-empty string")
        x = _as_int("x", args.get("x"))
        y = _as_int("y", args.get("y"))
        if x is None or y is None:
            raise ToolArgError("x and y are required")
        width = _positive_int("width", args.get("width"))
        height = _positive_int("height", args.get("height"))
        fill = _optional_hex("fill", args.get("fill"))
        outline = _optional_hex("outline", args.get("outline"))
        if fill is None and outline is None:
            raise ToolArgError("at least one of fill or outline is required")
        raw_stroke = args.get("stroke")
        if outline is not None:
            stroke = 1 if raw_stroke is None else _positive_int("stroke", raw_stroke)
        else:
            stroke = 1
        raw_radius = args.get("radius")
        if raw_radius is None:
            radius = 0
        else:
            radius = _as_int("radius", raw_radius)
            if radius is None or radius < 0:
                raise ToolArgError("radius must be an integer >= 0")

        src = _resolve_allowed(Path(raw_path.strip()), roots)
        dest = _alloc_png_path(out_root, "composed", "rect")
        return draw_rectangle(
            src,
            dest,
            x=int(x),
            y=int(y),
            width=width,
            height=height,
            fill=fill,
            outline=outline,
            stroke=stroke,
            radius=int(radius),
        ).as_dict()

    return ToolSpec(
        name="draw_rect",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to an existing PNG under allowed roots. "
                        "The input is not overwritten."
                    ),
                },
                "x": {"type": "integer", "description": "Left pixel of the rectangle."},
                "y": {"type": "integer", "description": "Top pixel of the rectangle."},
                "width": {"type": "integer", "description": "Rectangle width in pixels."},
                "height": {"type": "integer", "description": "Rectangle height in pixels."},
                "fill": {
                    "type": "string",
                    "description": "Optional fill as #RGB or #RRGGBB.",
                },
                "outline": {
                    "type": "string",
                    "description": "Optional stroke color as #RGB or #RRGGBB.",
                },
                "stroke": {
                    "type": "integer",
                    "description": "Outline width in pixels (default 1 if outline is set).",
                },
                "radius": {
                    "type": "integer",
                    "description": "Corner radius; 0 is sharp (default).",
                },
            },
            "required": ["path", "x", "y", "width", "height"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Draw a rectangle (gold frame, white plate; rounded if radius > 0) "
            "onto an existing PNG and write a new file under data/media/composed/. "
            "At least one of fill or outline is required. miss=file_not_found / "
            "unreadable / would_clip (fully outside; overhang is clipped)."
        ),
    )


def build_draw_text_tool(
    *,
    owner_agent: str,
    allowed_roots: tuple[Path, ...] | None = None,
    media_root: Path | None = None,
) -> ToolSpec:
    """Draw type onto an existing PNG; write a new composed PNG."""
    roots = allowed_roots if allowed_roots is not None else _DEFAULT_ALLOWED_ROOTS
    out_root = media_root if media_root is not None else _default_media_root()

    def handler(args: Mapping[str, Any]) -> Any:
        raw_path = args.get("path", "")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ToolArgError("path must be a non-empty string")
        raw_text = args.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ToolArgError("text must be a non-empty string")
        x = _as_int("x", args.get("x"))
        y = _as_int("y", args.get("y"))
        if x is None or y is None:
            raise ToolArgError("x and y are required")
        size = _positive_int("size", args.get("size"))
        color = _hex_color("color", args.get("color"))
        raw_font = args.get("font") or "serif"
        if not isinstance(raw_font, str) or raw_font not in _FONT_KINDS:
            raise ToolArgError("font must be serif, sans, or serif_italic")
        raw_align = args.get("align") or "left"
        if not isinstance(raw_align, str) or raw_align not in _ALIGN_KINDS:
            raise ToolArgError("align must be left, center, or right")
        raw_max = args.get("max_width")
        max_width = (
            None if raw_max is None else _positive_int("max_width", raw_max)
        )

        src = _resolve_allowed(Path(raw_path.strip()), roots)
        dest = _alloc_png_path(out_root, "composed", "text")
        return draw_text_on_image(
            src,
            dest,
            text=raw_text,
            x=int(x),
            y=int(y),
            size=size,
            color=color,
            font_kind=raw_font,
            align=raw_align,
            max_width=max_width,
        ).as_dict()

    return ToolSpec(
        name="draw_text",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to an existing PNG under allowed roots. "
                        "The input is not overwritten."
                    ),
                },
                "text": {"type": "string", "description": "Non-empty string to draw."},
                "x": {
                    "type": "integer",
                    "description": "Horizontal anchor (left / center / right of the text box).",
                },
                "y": {
                    "type": "integer",
                    "description": "Top of the text box (not the baseline).",
                },
                "size": {"type": "integer", "description": "Type size in points."},
                "color": {
                    "type": "string",
                    "description": "Type color as #RGB or #RRGGBB.",
                },
                "font": {
                    "type": "string",
                    "enum": ["serif", "sans", "serif_italic"],
                    "description": "serif (default), sans, or serif_italic.",
                },
                "align": {
                    "type": "string",
                    "enum": ["left", "center", "right"],
                    "description": "Horizontal anchor at x. Default left.",
                },
                "max_width": {
                    "type": "integer",
                    "description": "Optional wrap width in pixels.",
                },
            },
            "required": ["path", "text", "x", "y", "size", "color"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Draw type (serif / sans / serif_italic, hex color, left/center/right) "
            "onto an existing PNG and write a new file under data/media/composed/. "
            "x,y is the top of the text box. miss=file_not_found / unreadable."
        ),
    )


def register_qr_tools(
    registry: ToolRegistry,
    *,
    owner_agent: str,
    allowed_roots: tuple[Path, ...] | None = None,
    media_root: Path | None = None,
) -> None:
    """Register Eve's QR/canvas/type desk tools. Default owner is Eve."""
    registry.register(
        build_decode_qr_tool(
            owner_agent=owner_agent,
            allowed_roots=allowed_roots,
        )
    )
    registry.register(
        build_make_qr_tool(
            owner_agent=owner_agent,
            media_root=media_root,
        )
    )
    registry.register(
        build_compose_image_tool(
            owner_agent=owner_agent,
            allowed_roots=allowed_roots,
            media_root=media_root,
        )
    )
    registry.register(
        build_make_canvas_tool(
            owner_agent=owner_agent,
            media_root=media_root,
        )
    )
    registry.register(
        build_draw_rect_tool(
            owner_agent=owner_agent,
            allowed_roots=allowed_roots,
            media_root=media_root,
        )
    )
    registry.register(
        build_draw_text_tool(
            owner_agent=owner_agent,
            allowed_roots=allowed_roots,
            media_root=media_root,
        )
    )
