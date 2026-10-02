"""Route a receipt to a registered book or unsorted. Never guess."""

from __future__ import annotations

from dataclasses import dataclass
import re

from soveryn.plugins.api import BookDef


@dataclass(frozen=True)
class ClassifyHit:
    book: str  # soveryn | cwg | unsorted | <plugin book>
    gap: str | None = None
    reasons: tuple[str, ...] = ()


def _books() -> list[BookDef]:
    from soveryn.platform.ledgers.registry import all_books

    return all_books()


def _soveryn_book() -> BookDef | None:
    from soveryn.platform.ledgers.registry import get_book

    return get_book("soveryn")


def classify_receipt(filename: str, text: str) -> ClassifyHit:
    name = (filename or "").lower()
    blob = f"{filename}\n{text}".lower()
    books = _books()

    quote = _looks_like_quote(name, blob, books)
    if quote:
        return quote

    exclusive = _exclusive_domain_hit(blob, books)
    if exclusive is not None:
        return exclusive

    name_book = _filename_hint(name, books)
    hits = {book.id: _book_hit(book, name, blob) for book in books}
    cwg_hit = bool(hits.get("cwg"))
    sov_hit = bool(hits.get("soveryn"))

    if name_book == "cwg" and not sov_hit:
        return ClassifyHit(book="cwg", reasons=("filename",))
    if name_book == "soveryn" and not cwg_hit:
        return ClassifyHit(book="soveryn", reasons=("filename",))
    if name_book and cwg_hit and sov_hit:
        return ClassifyHit(
            book="unsorted",
            gap="filename and body point at different entities — do not guess",
            reasons=("conflict",),
        )

    if cwg_hit and sov_hit:
        return ClassifyHit(
            book="unsorted",
            gap=(
                "both SOVERYN and CWG signals present — do not guess. "
                "Pass splits=[{book, amount, description}, ...] to split the receipt"
            ),
            reasons=("conflict",),
        )
    if cwg_hit:
        return ClassifyHit(book="cwg", reasons=("text",))
    if sov_hit:
        return ClassifyHit(book="soveryn", reasons=("text",))
    if name_book:
        return ClassifyHit(book=name_book, reasons=("filename",))
    return ClassifyHit(
        book="unsorted",
        gap="no SOVERYN or CWG signal — drop in data/intake/ledgers/soveryn or cwg, or rename the file",
        reasons=("none",),
    )


def _book_hit(book: BookDef, name: str, blob: str) -> bool:
    if any(tok in blob for tok in book.classify_terms):
        return True
    if book.name_regex and re.search(book.name_regex, name, re.I):
        return True
    return False


def _filename_hint(name: str, books: list[BookDef]) -> str | None:
    matched: list[str] = []
    for book in books:
        if book.name_regex and re.search(book.name_regex, name, re.I):
            matched.append(book.id)
    if len(matched) != 1:
        return None
    return matched[0]


def _exclusive_domain_hit(blob: str, books: list[BookDef]) -> ClassifyHit | None:
    """Domain SKU beats the Cloudflare payer (SOVERYN LLC often pays CWG DNS)."""
    sov = _soveryn_book()
    sov_domains = tuple(sov.domain_signals) if sov else ()
    for book in books:
        if not book.exclusive_domain or not book.domain_signals:
            continue
        if any(dom in blob for dom in book.domain_signals) and not any(
            other in blob for other in sov_domains
        ):
            return ClassifyHit(book=book.id, reasons=(f"{book.id}-domain",))
    return None


def _looks_like_quote(
    name: str, blob: str, books: list[BookDef]
) -> ClassifyHit | None:
    needles: list[str] = []
    for book in books:
        needles.extend(book.quote_needles)
    if not needles:
        return None
    if "pondwright" in blob and "quote" in blob:
        return ClassifyHit(
            book="unsorted",
            gap="Pondwright/CWG quote is not a tax receipt — keep out of both books",
            reasons=("quote",),
        )
    if "quote" in name and (
        "carolina water" in blob or "pondwright" in blob or "pond package" in blob
    ):
        return ClassifyHit(
            book="unsorted",
            gap="Pondwright/CWG quote is not a tax receipt — keep out of both books",
            reasons=("quote",),
        )
    if "quote for" in blob and "carolina water" in blob:
        return ClassifyHit(
            book="unsorted",
            gap="Pondwright/CWG quote is not a tax receipt — keep out of both books",
            reasons=("quote",),
        )
    return None
