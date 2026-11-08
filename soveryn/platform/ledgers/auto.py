"""Preview a chat photo when Jon names CWG or SOVERYN. Never auto-book."""

from __future__ import annotations

import base64
import os
import re
import tempfile
from pathlib import Path

from soveryn.platform.ledgers.ingest import ingest_path
from soveryn.platform.vision_types import ALLOWED_IMAGE_MIME_PREFIXES

_FILE_INTENT = re.compile(
    r"\b(file|log|book|ingest|receipt|expense|ledger|tax)\b",
    re.I,
)
_SOVERYN = re.compile(r"\bsoveryn\b|\bsovery\b", re.I)


def _chat_regex(book_id: str) -> re.Pattern[str] | None:
    from soveryn.platform.ledgers.registry import get_book

    book = get_book(book_id)
    if book is None or not book.chat_regex:
        return None
    return re.compile(book.chat_regex, re.I)


def receipt_file_book(message: str) -> str | None:
    """Which book the turn *names*. Not authorization to write the book."""
    text = message or ""
    if not _FILE_INTENT.search(text):
        return None
    cwg_rx = _chat_regex("cwg")
    cwg = bool(cwg_rx.search(text)) if cwg_rx is not None else False
    sov = bool(_SOVERYN.search(text))
    if cwg and not sov:
        return "cwg"
    if sov and not cwg:
        return "soveryn"
    return None


def apply_chat_receipt(message: str, image_data_urls: tuple[str, ...]) -> str | None:
    """Preview-only splice. Does not book, copy evidence, or write intake."""
    book = receipt_file_book(message)
    if not book or not image_data_urls:
        return None
    dest = _save_preview_image(image_data_urls[0])
    result = ingest_path(
        dest,
        book=book,
        folder_hint=book,
        confirm=False,
        actor="chat_receipt_preview",
    )
    token = result.confirm_token or ""
    return (
        "[Ledger ingest]\n"
        f"book={result.book} action={result.action} "
        f"amount={result.amount_usd or 'NONE'} "
        f"order={result.order_id or '-'} "
        f"evidence={result.evidence or '-'} "
        f"gap={result.gap or 'none'}\n"
        f"confirm_token={token or '-'}\n"
        f"{result.message}\n"
        "PREVIEW ONLY — ledger CSV and evidence were not written. "
        "Naming CWG or SOVERYN classifies the book; it does not authorize a booking. "
        "This chat token cannot book. Call ledger_ingest to preview "
        "(add corrections if OCR invoice/description/category/payment/vendor/"
        "cash is wrong; vendor/amount_usd need review_provenance), "
        "then confirm=true with THAT token. Do not book an uncorrected preview. "
        "Report these facts. Do not create_document. Do not invent a second filing."
    )


def _save_preview_image(url: str) -> Path:
    """Decode to a temp file for OCR. Not intake, not evidence."""
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
    fd, name = tempfile.mkstemp(prefix="chat-receipt-preview-", suffix=suffix)
    os.close(fd)
    dest = Path(name)
    dest.write_bytes(data)
    return dest
