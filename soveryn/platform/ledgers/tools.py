"""Agent tool: drop a receipt (PDF or photo) onto the SOVERYN or CWG tax book."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from soveryn.platform.intake.tools import _DEFAULT_ALLOWED_ROOTS, _resolve_allowed
from soveryn.platform.intake.turn_files import parse_current_index, pick_current
from soveryn.platform.intake.turn_images import current_turn_images
from soveryn.platform.ledgers.extract import RECEIPT_SUFFIXES
from soveryn.platform.ledgers.ingest import (
    ingest_drop,
    ingest_path,
    normalize_splits,
    split_existing_order,
)
from soveryn.platform.ledgers.paths import drop_root, ensure_drop_dirs
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec
from soveryn.platform.vision_types import ALLOWED_IMAGE_MIME_PREFIXES

_BOOKS = frozenset({"soveryn", "cwg", "auto"})


def _decode_data_url(url: str) -> tuple[bytes, str]:
    if not url.startswith(ALLOWED_IMAGE_MIME_PREFIXES):
        raise ToolArgError("image must be a data:image/{jpeg,png,webp,gif} URL")
    header, _, payload = url.partition(",")
    if not payload:
        raise ToolArgError("image data URL is missing payload")
    try:
        data = base64.b64decode(payload, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise ToolArgError(f"image data URL is not valid base64: {exc}") from exc
    if "jpeg" in header or "jpg" in header:
        suffix = ".jpg"
    elif "png" in header:
        suffix = ".png"
    elif "webp" in header:
        suffix = ".webp"
    else:
        suffix = ".jpg"
    return data, suffix


def _save_current_file(*, book: str, src: str) -> Path:
    hit = pick_current(src)
    if hit is None:
        raise ToolArgError(
            "no in-flight PDF on this turn — attach the file in chat "
            "and pass path=current (current:2 for the second). "
            "Do not look for attachment-1.pdf on disk."
        )
    folder = book if book in {"soveryn", "cwg"} else "unsorted"
    dest_dir = ensure_drop_dirs() / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = Path(hit.name).suffix.lower() or ".pdf"
    if suffix not in RECEIPT_SUFFIXES:
        suffix = ".pdf"
    dest = dest_dir / f"chat-{stamp}{suffix}"
    dest.write_bytes(hit.data)
    return dest


def _save_current_photo(*, book: str) -> Path:
    urls = current_turn_images()
    if not urls:
        raise ToolArgError(
            "no photo on this turn — attach a receipt picture or pass path"
        )
    data, suffix = _decode_data_url(urls[0])
    folder = book if book in {"soveryn", "cwg"} else "unsorted"
    dest_dir = ensure_drop_dirs() / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"chat-{stamp}{suffix}"
    dest.write_bytes(data)
    return dest


def build_ledger_ingest_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        raw = args.get("path", "")
        raw_image = args.get("image", "")
        raw_book = args.get("book", "auto")
        raw_order = args.get("order_id", "")
        raw_splits = args.get("splits")
        if raw is not None and not isinstance(raw, str):
            raise ToolArgError("path must be a string")
        if raw_image is not None and not isinstance(raw_image, str):
            raise ToolArgError("image must be a string")
        if raw_book is not None and not isinstance(raw_book, str):
            raise ToolArgError("book must be a string")
        if raw_order is not None and not isinstance(raw_order, str):
            raise ToolArgError("order_id must be a string")
        path_s = raw.strip() if isinstance(raw, str) else ""
        image_s = raw_image.strip() if isinstance(raw_image, str) else ""
        order_id = raw_order.strip() if isinstance(raw_order, str) else ""
        book = (raw_book or "auto").strip().lower() or "auto"
        if book not in _BOOKS:
            raise ToolArgError("book must be soveryn, cwg, or auto")
        forced = None if book == "auto" else book
        splits = None
        if raw_splits is not None:
            if not isinstance(raw_splits, list):
                raise ToolArgError(
                    "splits must be a list of {book, amount, description}"
                )
            try:
                splits = normalize_splits(raw_splits)
            except ValueError as exc:
                raise ToolArgError(str(exc)) from exc

        if splits and order_id and not path_s and image_s.lower() != "current" and parse_current_index(path_s) is None:
            return split_existing_order(order_id, splits).as_dict()

        if parse_current_index(path_s) is not None:
            saved = _save_current_file(book=book, src=path_s)
            return ingest_path(
                saved,
                folder_hint=forced,
                book=forced,
                splits=splits,
            ).as_dict()

        if image_s.lower() == "current" or (image_s and not path_s):
            if image_s.lower() != "current" and image_s:
                raise ToolArgError('image must be "current" for a chat photo')
            saved = _save_current_photo(book=book)
            return ingest_path(
                saved,
                folder_hint=forced,
                book=forced,
                splits=splits,
            ).as_dict()

        if path_s:
            p = _resolve_allowed(Path(path_s), _DEFAULT_ALLOWED_ROOTS)
            if not p.is_file():
                raise ToolArgError(f"path is not a file: {p}")
            if p.suffix.lower() not in RECEIPT_SUFFIXES:
                raise ToolArgError(
                    "ledger_ingest accepts PDF or a photo (jpg/png/webp)"
                )
            return ingest_path(
                p, folder_hint=forced, book=forced, splits=splits
            ).as_dict()

        if splits:
            raise ToolArgError(
                "splits need path, image=\"current\", or order_id of an already-filed receipt"
            )

        ensure_drop_dirs()
        results = ingest_drop()
        return {
            "ok": True,
            "drop": str(drop_root()),
            "results": [r.as_dict() for r in results],
            "count": len(results),
        }

    return ToolSpec(
        name="ledger_ingest",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path, or 'current' / 'current:2' for a PDF "
                        "Jon just attached in this chat turn. "
                        "Omit with image=\"current\" for a picture."
                    ),
                },
                "image": {
                    "type": "string",
                    "description": (
                        "Pass \"current\" to file the photo Jon just sent on "
                        "this Messages turn (Expensify-style). OCR the snap; "
                        "never invent a garbled total."
                    ),
                },
                "book": {
                    "type": "string",
                    "enum": ["soveryn", "cwg", "auto"],
                    "description": (
                        "soveryn or cwg when Jon says which business. "
                        "auto (default) classifies from the file/OCR. "
                        "Unsorted if unclear — do not guess. "
                        "Do not file the same full total on both books."
                    ),
                },
                "order_id": {
                    "type": "string",
                    "description": (
                        "Amazon/eBay/etc order id when splitting a receipt "
                        "already on the books (no file needed)."
                    ),
                },
                "splits": {
                    "type": "array",
                    "description": (
                        "When one receipt has items for both businesses, "
                        "list each line Jon named. Example: "
                        "[{book:\"cwg\", amount:\"22.30\", "
                        "description:\"Aquascape potting media\"}, "
                        "{book:\"soveryn\", amount:\"69.90\", "
                        "description:\"Tecmojo 6U rack\"}]. "
                        "Do not invent amounts. Do not put the full cash "
                        "total on both books."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "book": {
                                "type": "string",
                                "enum": ["soveryn", "cwg"],
                            },
                            "amount": {"type": "string"},
                            "amount_usd": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["book"],
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "File a receipt onto the SOVERYN or CWG tax ledger. "
            "PDF print or a photo in chat (image=\"current\"), like Expensify. "
            "Pass book=cwg or book=soveryn when Jon names the entity. "
            "One receipt, two businesses: pass splits with each line's "
            "book/amount/description (and path or order_id). Never book the "
            "full total on both. Always use this for receipts — never "
            "create_document. Cite-or-stop on garbled totals. Does not file a return."
        ),
    )


def register_ledger_tools(registry: ToolRegistry, *, owner_agent: str) -> None:
    registry.register(build_ledger_ingest_tool(owner_agent=owner_agent))
