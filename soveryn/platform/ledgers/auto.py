"""Auto-file a chat photo when Jon says to put it on CWG or SOVERYN."""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from pathlib import Path

from soveryn.platform.ledgers.ingest import ingest_path
from soveryn.platform.ledgers.paths import ensure_drop_dirs
from soveryn.platform.vision_types import ALLOWED_IMAGE_MIME_PREFIXES

_FILE_INTENT = re.compile(
    r"\b(file|log|book|ingest|receipt|expense|ledger|tax)\b",
    re.I,
)
_CWG = re.compile(r"\bcwg\b|carolina water", re.I)
_SOVERYN = re.compile(r"\bsoveryn\b|\bsovery\b", re.I)


def receipt_file_book(message: str) -> str | None:
    """Return soveryn/cwg when this turn is 'file this receipt on X'."""
    text = message or ""
    if not _FILE_INTENT.search(text):
        return None
    cwg = bool(_CWG.search(text))
    sov = bool(_SOVERYN.search(text))
    if cwg and not sov:
        return "cwg"
    if sov and not cwg:
        return "soveryn"
    return None


def apply_chat_receipt(message: str, image_data_urls: tuple[str, ...]) -> str | None:
    """Save the snap, ingest, return a splice block for the model. None if N/A."""
    book = receipt_file_book(message)
    if not book or not image_data_urls:
        return None
    dest = _save_data_url(image_data_urls[0], book)
    result = ingest_path(dest, book=book, folder_hint=book)
    return (
        "[Ledger ingest]\n"
        f"book={result.book} action={result.action} "
        f"amount={result.amount_usd or 'NONE'} "
        f"order={result.order_id or '-'} "
        f"evidence={result.evidence or '-'} "
        f"gap={result.gap or 'none'}\n"
        f"{result.message}\n"
        "Report these facts. Do not create_document. Do not invent a second filing."
    )


def _save_data_url(url: str, book: str) -> Path:
    if not url.startswith(ALLOWED_IMAGE_MIME_PREFIXES):
        raise ValueError("chat receipt is not a data:image URL")
    header, _, payload = url.partition(",")
    data = base64.b64decode(payload, validate=False)
    if "png" in header:
        suffix = ".png"
    elif "webp" in header:
        suffix = ".webp"
    else:
        suffix = ".jpg"
    dest_dir = ensure_drop_dirs() / book
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"chat-{stamp}{suffix}"
    dest.write_bytes(data)
    return dest
