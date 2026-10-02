"""Tax-book registry — SOVERYN book in core, others from plugins."""

from __future__ import annotations

from pathlib import Path

from soveryn.plugins.api import BookDef

SOVERYN_BOOK = BookDef(
    id="soveryn",
    csv_rel="docs/ops/tax/SOVERYN-2025-2026-expense-ledger.csv",
    evidence_rel="docs/ops/tax/evidence",
    classify_terms=(
        "nvidia",
        "quadro",
        "rtx ",
        "rtx-",
        "blackwell",
        "epyc",
        "dgx",
        "gx10",
        "spark 1",
        "spark 2",
        "dgx spark",
        "nemix",
        "anthropic",
        "claude max",
        "xai",
        "supergrok",
        "soveryn intelligence",
        "soverynintelligence",
        "connectx",
        "asrock",
        "deco gear",
        "smttr",
        "newegg",
        "openai",
        "chatgpt",
        "tecmojo",
        "network rack",
        "server rack",
    ),
    name_regex=r"soveryn|sovery",
    domain_signals=("soverynintelligence.com", "soverynintelligence.ai"),
)

_BOOKS: dict[str, BookDef] = {"soveryn": SOVERYN_BOOK}
_PLUGIN_LOADED = False


def register_book(book: BookDef) -> None:
    _BOOKS[book.id] = book


def reset_plugin_books() -> None:
    global _PLUGIN_LOADED
    _BOOKS.clear()
    _BOOKS["soveryn"] = SOVERYN_BOOK
    _PLUGIN_LOADED = False


def _ensure_plugin_books() -> None:
    global _PLUGIN_LOADED
    if _PLUGIN_LOADED:
        return
    _PLUGIN_LOADED = True
    if "soveryn" not in _BOOKS:
        _BOOKS["soveryn"] = SOVERYN_BOOK
    from soveryn.plugins.loader import plugin_ledger_books

    for book in plugin_ledger_books():
        register_book(book)


def get_book(book_id: str) -> BookDef | None:
    _ensure_plugin_books()
    return _BOOKS.get((book_id or "").strip().lower())


def all_books() -> list[BookDef]:
    _ensure_plugin_books()
    return list(_BOOKS.values())


def book_ids() -> frozenset[str]:
    _ensure_plugin_books()
    return frozenset(_BOOKS)


def resolve_csv(book_id: str, root: Path | None = None) -> Path | None:
    from soveryn.platform.ledgers.paths import repo_root

    book = get_book(book_id)
    if book is None:
        return None
    return book.csv_path(root or repo_root())


def resolve_evidence(book_id: str, root: Path | None = None) -> Path | None:
    from soveryn.platform.ledgers.paths import repo_root

    book = get_book(book_id)
    if book is None:
        return None
    return book.evidence_path(root or repo_root())
