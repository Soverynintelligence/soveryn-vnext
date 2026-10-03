"""Agent tools: preview/confirm ingest, preview/confirm amend, read-only reconcile."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from soveryn.platform.intake.tools import DEFAULT_ALLOWED_ROOTS, resolve_allowed
from soveryn.platform.intake.turn_files import parse_current_index, pick_current
from soveryn.platform.intake.turn_images import current_turn_images
from soveryn.platform.ledgers.books import amend_row
from soveryn.platform.ledgers.extract import RECEIPT_SUFFIXES
from soveryn.platform.ledgers.ingest import (
    ingest_path,
    normalize_splits,
    split_existing_order,
)
from soveryn.platform.ledgers.paths import ensure_drop_dirs
from soveryn.platform.ledgers.reconcile import audit_books
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec
from soveryn.platform.vision_types import ALLOWED_IMAGE_MIME_PREFIXES


def _book_choices() -> frozenset[str]:
    from soveryn.platform.ledgers.registry import book_ids

    return frozenset(book_ids()) | {"auto"}


def _split_books() -> frozenset[str]:
    from soveryn.platform.ledgers.registry import book_ids

    return frozenset(book_ids())


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
    folder = book if book in _split_books() else "unsorted"
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
    folder = book if book in _split_books() else "unsorted"
    dest_dir = ensure_drop_dirs() / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"chat-{stamp}{suffix}"
    dest.write_bytes(data)
    return dest


def _as_bool(raw: Any, *, name: str) -> bool:
    if raw is None or raw is False:
        return False
    if raw is True:
        return True
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    raise ToolArgError(f"{name} must be a boolean")


def _ingest_kwargs(args: Mapping[str, Any]) -> dict[str, Any]:
    confirm = _as_bool(args.get("confirm"), name="confirm")
    token = args.get("confirm_token", "")
    override = args.get("override_reason", "")
    if token is not None and not isinstance(token, str):
        raise ToolArgError("confirm_token must be a string")
    if override is not None and not isinstance(override, str):
        raise ToolArgError("override_reason must be a string")
    token_s = token.strip() if isinstance(token, str) else ""
    override_s = override.strip() if isinstance(override, str) else ""
    if confirm and not token_s:
        raise ToolArgError(
            "confirm=true requires the confirm_token from the preview call"
        )
    return {
        "confirm": confirm,
        "confirm_token": token_s or None,
        "override_reason": override_s or None,
        "actor": "ledger_ingest",
    }


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
        if book not in _book_choices():
            allowed = ", ".join(sorted(_book_choices()))
            raise ToolArgError(f"book must be {allowed.replace('auto', 'or auto')}")
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
        extra = _ingest_kwargs(args)

        if splits and order_id and not path_s and image_s.lower() != "current" and parse_current_index(path_s) is None:
            return split_existing_order(
                order_id,
                splits,
                confirm=extra["confirm"],
                override_reason=extra["override_reason"],
                actor=extra["actor"],
            ).as_dict()

        if order_id and not splits and not path_s and not image_s:
            raise ToolArgError(
                "order_id alone does not edit a filed row — pass splits to "
                "split it, or path/current to file a receipt"
            )

        if parse_current_index(path_s) is not None:
            saved = _save_current_file(book=book, src=path_s)
            return ingest_path(
                saved,
                folder_hint=forced,
                book=forced,
                splits=splits,
                **extra,
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
                **extra,
            ).as_dict()

        if path_s:
            p = resolve_allowed(Path(path_s), DEFAULT_ALLOWED_ROOTS)
            if not p.is_file():
                raise ToolArgError(f"path is not a file: {p}")
            if p.suffix.lower() not in RECEIPT_SUFFIXES:
                raise ToolArgError(
                    "ledger_ingest accepts PDF or a photo (jpg/png/webp)"
                )
            return ingest_path(
                p, folder_hint=forced, book=forced, splits=splits, **extra
            ).as_dict()

        if splits:
            raise ToolArgError(
                "splits need path, image=\"current\", or order_id of an already-filed receipt"
            )

        raise ToolArgError(
            "ledger_ingest refuses folder-wide ingest — pass path, "
            "image=\"current\", or order_id+splits for a specific item"
        )

    return ToolSpec(
        name="ledger_ingest",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to one receipt, or 'current' / 'current:2' "
                        "for a PDF Jon just attached. Required unless image or "
                        "order_id+splits. Folder-wide ingest is refused."
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
                    "enum": sorted(_book_choices(), key=lambda n: (n != "soveryn", n != "cwg", n)),
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
                        "already on the books (no file needed). Alone is an error."
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
                                "enum": sorted(_split_books(), key=lambda n: (n != "soveryn", n != "cwg", n)),
                            },
                            "amount": {"type": "string"},
                            "amount_usd": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["book"],
                        "additionalProperties": False,
                    },
                },
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "Default false: return a preview of the rows that would "
                        "be added plus a short-lived confirm_token. Writes only "
                        "when confirm=true and that token is returned."
                    ),
                },
                "confirm_token": {
                    "type": "string",
                    "description": (
                        "Token from the preview call. Required with confirm=true."
                    ),
                },
                "override_reason": {
                    "type": "string",
                    "description": (
                        "Required to book when subtotal+shipping+tax-discount "
                        "does not match the printed total within a cent. "
                        "Logged in the change log."
                    ),
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Preview, then confirm, a receipt onto the SOVERYN or CWG tax ledger. "
            "First call (confirm omitted/false) returns the exact rows that would "
            "be added and a short-lived confirm_token; it writes nothing. "
            "Second call with confirm=true and that token writes through the "
            "single locked book writer. Name a specific file "
            "(path, image=\"current\", or order_id+splits) — folder-wide "
            "re-ingest is refused. Re-submitting the same receipt is a safe "
            "no-op that returns the existing row. Totals that do not match "
            "within a cent are blocked unless override_reason is given. "
            "One receipt, two businesses: pass splits. Never create_document. "
            "Cite-or-stop on garbled totals. Does not file a return. "
            "Use ledger_amend to edit/remove a row; ledger_reconcile to audit."
        ),
    )


def build_ledger_amend_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        raw_book = args.get("book", "")
        raw_id = args.get("row_id", "")
        raw_reason = args.get("reason", "")
        raw_remove = args.get("remove", False)
        raw_updates = args.get("updates")
        confirm = _as_bool(args.get("confirm"), name="confirm")
        if not isinstance(raw_book, str) or not raw_book.strip():
            raise ToolArgError("book is required (soveryn or cwg)")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise ToolArgError("row_id is required")
        if not isinstance(raw_reason, str) or not raw_reason.strip():
            raise ToolArgError("reason is required")
        book = raw_book.strip().lower()
        if book not in _split_books():
            raise ToolArgError("book must be soveryn or cwg")
        remove = _as_bool(raw_remove, name="remove")
        updates: dict[str, str] | None = None
        if raw_updates is not None:
            if not isinstance(raw_updates, Mapping):
                raise ToolArgError("updates must be an object of column=value")
            updates = {str(k): "" if v is None else str(v) for k, v in raw_updates.items()}
        from soveryn.platform.ledgers.registry import resolve_csv

        csv_path = resolve_csv(book)
        if csv_path is None:
            raise ToolArgError(f"unknown book: {book}")
        try:
            return amend_row(
                csv_path,
                raw_id.strip(),
                reason=raw_reason.strip(),
                updates=updates,
                remove=remove,
                actor="ledger_amend",
                confirm=confirm,
            )
        except ValueError as exc:
            raise ToolArgError(str(exc)) from exc

    return ToolSpec(
        name="ledger_amend",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "book": {
                    "type": "string",
                    "enum": sorted(_split_books(), key=lambda n: (n != "soveryn", n != "cwg", n)),
                    "description": "Which book holds the row.",
                },
                "row_id": {
                    "type": "string",
                    "description": "Stable row_id from the book (end columns).",
                },
                "reason": {
                    "type": "string",
                    "description": "Required. Written to the change log.",
                },
                "remove": {
                    "type": "boolean",
                    "description": (
                        "If true, archive the row to duplicates-removed-*.csv "
                        "beside the book and drop it from the live CSV. "
                        "Never a silent delete."
                    ),
                },
                "updates": {
                    "type": "object",
                    "description": "Column=value edits. Cannot change row_id.",
                    "additionalProperties": {"type": "string"},
                },
                "confirm": {
                    "type": "boolean",
                    "description": (
                        "Default false: return a preview of the row, "
                        "field-by-field before/after, and the would-be counted "
                        "total change. Writes nothing. Writes only when "
                        "confirm=true (same flag as ledger_ingest)."
                    ),
                },
            },
            "required": ["book", "row_id", "reason"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Preview, then confirm, an edit or remove of one tax-book row by "
            "row_id. First call (confirm omitted/false) returns the row, "
            "field-by-field before/after, and the would-be counted total "
            "change; it writes nothing. Second call with confirm=true writes "
            "through the single locked writer. Reason is required and is "
            "written to <book>.changes.jsonl. Removed rows are archived to "
            "duplicates-removed-*.csv beside the book — never silently "
            "deleted. Does not ingest."
        ),
    )


def build_ledger_reconcile_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        raw_book = args.get("book", "")
        if raw_book is not None and not isinstance(raw_book, str):
            raise ToolArgError("book must be a string")
        wanted = (raw_book or "").strip().lower()
        from soveryn.platform.ledgers.registry import all_books, book_ids

        if wanted and wanted not in book_ids():
            raise ToolArgError("book must be soveryn, cwg, or omitted for both")
        chosen = [b for b in all_books() if not wanted or b.id == wanted]
        from soveryn.platform.ledgers.paths import repo_root

        base = repo_root()
        books = {b.id: b.csv_path(base) for b in chosen}
        evidence = {b.id: b.evidence_path(base) for b in chosen}
        return audit_books(books, evidence)

    return ToolSpec(
        name="ledger_reconcile",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "book": {
                    "type": "string",
                    "enum": sorted(_split_books(), key=lambda n: (n != "soveryn", n != "cwg", n)),
                    "description": "Optional. Omit to audit every registered book.",
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Read-only audit of the tax books. Reports likely duplicates "
            "(same evidence_sha256, same order_id, or same date+vendor+amount), "
            "rows whose evidence files are missing, evidence files no row "
            "references, and per-book counts and totals. EXCLUDE rows stay "
            "visible (excluded_rows / excluded_usd). total_usd is the raw sum "
            "of every row; counted_usd skips EXCLUDE. Excluded rows are "
            "omitted from duplicate grouping; their evidence still counts as "
            "referenced. Writes nothing."
        ),
    )


def register_ledger_tools(registry: ToolRegistry, *, owner_agent: str) -> None:
    registry.register(build_ledger_ingest_tool(owner_agent=owner_agent))
    registry.register(build_ledger_amend_tool(owner_agent=owner_agent))
    registry.register(build_ledger_reconcile_tool(owner_agent=owner_agent))
