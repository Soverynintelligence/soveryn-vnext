"""Copy evidence and append to the matching book. Unsorted when unsure."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
from typing import Any, Callable, Mapping, Sequence

from soveryn.platform.intake.pdf import ExtractResult
from soveryn.platform.ledgers.books import (
    ChangeRecord,
    CSV_FIELDS,
    exclusive_book,
    find_duplicate,
    has_order_id,
    load_rows,
    new_row_id,
    rows_for_order,
    without_order,
    write_book,
)
from soveryn.platform.ledgers.classify import classify_receipt
from soveryn.platform.ledgers.extract import RECEIPT_SUFFIXES, extract_receipt_path
from soveryn.platform.ledgers.parse import ParsedRow, parse_receipt
from soveryn.platform.ledgers.parse import _schedule as schedule_for
from soveryn.platform.ledgers.paths import (
    ensure_drop_dirs,
    repo_root,
)

ExtractFn = Callable[[Path], ExtractResult]

CONFIRM_TTL_SECONDS = 15 * 60
FOLDER_WIDE_REFUSED = (
    "folder-wide ingest is refused — name specific files or items"
)

_CONFIRM_LOCK = threading.Lock()
_CONFIRM: dict[str, dict[str, Any]] = {}


def _registered_book_paths() -> dict[str, Path]:
    from soveryn.platform.ledgers.registry import all_books

    base = repo_root()
    return {b.id: b.csv_path(base) for b in all_books()}


def _registered_evidence_roots() -> dict[str, Path]:
    from soveryn.platform.ledgers.registry import all_books

    base = repo_root()
    return {b.id: b.evidence_path(base) for b in all_books()}


@dataclass(frozen=True)
class SplitSpec:
    book: str
    amount_usd: str
    description: str = ""


@dataclass
class IngestResult:
    book: str
    action: str
    source_name: str
    order_id: str | None = None
    amount_usd: str = ""
    evidence: str | None = None
    gap: str | None = None
    message: str = ""
    splits: list[dict[str, str]] = field(default_factory=list)
    row: dict[str, str] | None = None
    rows: list[dict[str, str]] = field(default_factory=list)
    confirm_token: str | None = None
    confirm_expires_at: str | None = None
    ocr: dict[str, str] | None = None
    ocr_gap: str | None = None
    corrections: dict[str, str] | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


# Reviewed pre-booking fields. Raw OCR money lines are immutable diagnostics.
# amount_usd is the effective cash snapshot and requires image-review provenance.
_CORRECTION_ALIASES = {
    "invoice": "order_id",
    "order_id": "order_id",
    "description": "description",
    "category": "schedule_c_or_form",
    "schedule_c_or_form": "schedule_c_or_form",
    "payment": "payment_method",
    "payment_method": "payment_method",
    "purpose": "purpose",
    "vendor": "vendor",
    "amount_usd": "amount_usd",
    "review_provenance": "review_provenance",
    "review_rationale": "review_rationale",
}
_CORRECTION_ORDER = (
    "order_id",
    "description",
    "schedule_c_or_form",
    "payment_method",
    "purpose",
    "vendor",
    "amount_usd",
    "review_provenance",
    "review_rationale",
)
_CORRECTION_LIMITS = {
    "order_id": 40,
    "description": 300,
    "schedule_c_or_form": 80,
    "payment_method": 80,
    "purpose": 300,
    "vendor": 80,
    "amount_usd": 16,
    "review_provenance": 80,
    "review_rationale": 300,
}
_RAW_MONEY_CORRECTION_FIELDS = frozenset(
    {
        "amount",
        "subtotal",
        "tax",
        "shipping",
        "discount",
        "printed_total",
        "total",
    }
)
_REVIEW_PROVENANCE_ALLOWED = frozenset({"operator reviewed source image"})
_FILENAME_INFERENCE = re.compile(
    r"\b(filename|file name|from the name|inferred from (the )?name)\b",
    re.I,
)
_FILENAME_ONLY = re.compile(
    r"^[\w.\-]+\.(jpg|jpeg|png|webp|pdf|tif|tiff)$",
    re.I,
)
_CENTS_RE = re.compile(r"^(?:0|[1-9][0-9]*)\.[0-9]{2}$")
_REVIEW_CASH_FIELDS = ("vendor", "amount_usd")
_MAX_CENTS = Decimal("999999.99")
_SEMANTIC_FIELDS = (
    "order_id",
    "description",
    "schedule_c_or_form",
    "payment_method",
    "notes",
    "amount_usd",
    "date",
    "vendor",
    "status",
)
_OCR_FIELDS = (
    "order_id",
    "description",
    "schedule_c_or_form",
    "payment_method",
    "amount_usd",
    "date",
    "vendor",
    "status",
    "subtotal",
    "tax",
    "shipping",
    "discount",
    "printed_total",
    "card_amount",
    "notes",
    "gap",
)
_OCR_MONEY_BIND = (
    "amount_usd",
    "vendor",
    "status",
    "subtotal",
    "tax",
    "shipping",
    "discount",
    "printed_total",
    "card_amount",
)


def canonical_cents(raw: str) -> str:
    """Exact positive cents. Reject exponents, extra precision, nonfinite."""
    if not isinstance(raw, str):
        raise ValueError("corrections.amount_usd must be a string")
    text = raw.strip()
    if not _CENTS_RE.fullmatch(text):
        raise ValueError(
            "corrections.amount_usd must be a canonical cents string "
            "(e.g. '90.92'); $, commas, signs, exponents, and extra "
            "precision are rejected"
        )
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("corrections.amount_usd is not a finite decimal") from exc
    if not value.is_finite():
        raise ValueError("corrections.amount_usd must be finite")
    if value <= 0:
        raise ValueError("corrections.amount_usd must be positive")
    if value > _MAX_CENTS:
        raise ValueError("corrections.amount_usd exceeds bound")
    canon = format(value.quantize(Decimal("0.01")), "f")
    if canon != text:
        raise ValueError("corrections.amount_usd must be the canonical cents string")
    return canon


def _normalize_review_provenance(text: str) -> str:
    lowered = text.casefold()
    if lowered not in _REVIEW_PROVENANCE_ALLOWED:
        raise ValueError(
            "corrections.review_provenance must be "
            "'operator reviewed source image' — not filename inference"
        )
    return "operator reviewed source image"


def _normalize_review_rationale(text: str) -> str:
    if _FILENAME_INFERENCE.search(text) or _FILENAME_ONLY.fullmatch(text):
        raise ValueError(
            "corrections.review_rationale must be operator review of the "
            "source image, not filename inference"
        )
    return text


def normalize_corrections(raw: Mapping[str, object] | None) -> dict[str, str]:
    """Canonical reviewed-field map. Raw OCR money lines cannot be rewritten."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("corrections must be an object of field=value")
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if name in _RAW_MONEY_CORRECTION_FIELDS:
            raise ValueError(
                f"corrections.{name} is not supported — raw OCR subtotal/tax/"
                "printed_total stay diagnostic; reviewed amount_usd is the "
                "effective cash snapshot and cannot fake those lines"
            )
        canon = _CORRECTION_ALIASES.get(name)
        if canon is None:
            raise ValueError(
                f"unknown correction field {name!r}; supported: invoice, "
                "description, category, payment, purpose, vendor, amount_usd, "
                "review_provenance, review_rationale"
            )
        if not isinstance(value, str):
            raise ValueError(f"corrections.{name} must be a string")
        text = re.sub(r"\s+", " ", value).strip()
        if not text:
            raise ValueError(f"corrections.{name} must not be empty")
        if len(text) > _CORRECTION_LIMITS[canon]:
            raise ValueError(f"corrections.{name} is too long")
        if canon == "amount_usd":
            text = canonical_cents(text)
        elif canon == "vendor":
            if text.casefold() == "unknown":
                raise ValueError("corrections.vendor cannot be unknown")
        elif canon == "review_provenance":
            text = _normalize_review_provenance(text)
        elif canon == "review_rationale":
            text = _normalize_review_rationale(text)
        if canon in out and out[canon] != text:
            raise ValueError(f"corrections.{name} conflicts with another alias")
        out[canon] = text
    needs_review = any(field in out for field in _REVIEW_CASH_FIELDS)
    has_provenance = "review_provenance" in out
    has_rationale = "review_rationale" in out
    if needs_review and not (has_provenance and has_rationale):
        raise ValueError(
            "vendor/amount_usd corrections require review_provenance "
            "('operator reviewed source image') and review_rationale; "
            "purpose and override_reason are not permission"
        )
    if (has_provenance or has_rationale) and not needs_review:
        raise ValueError(
            "review_provenance/review_rationale apply only with vendor or "
            "amount_usd"
        )
    return {key: out[key] for key in _CORRECTION_ORDER if key in out}


def _ocr_fields(parsed: ParsedRow) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in _OCR_FIELDS:
        value = getattr(parsed, key, None)
        out[key] = "" if value is None else str(value)
    return out


def _ocr_money_fields(parsed: ParsedRow) -> dict[str, str]:
    ocr = _ocr_fields(parsed)
    return {key: ocr.get(key) or "" for key in _OCR_MONEY_BIND}


def _semantic_fields(row: Mapping[str, str]) -> dict[str, str]:
    return {key: (row.get(key) or "") for key in _SEMANTIC_FIELDS}


def _breakdown_total(row: Mapping[str, str]) -> Decimal | None:
    subtotal = _money0(row.get("subtotal") or "")
    if subtotal is None:
        return None
    shipping = _money0(row.get("shipping") or "") or Decimal("0.00")
    tax = _money0(row.get("tax") or "") or Decimal("0.00")
    discount = _money0(row.get("discount") or "") or Decimal("0.00")
    return (subtotal + shipping + tax - discount).quantize(Decimal("0.01"))


def operator_amount_conflicts_breakdown(row: Mapping[str, str], amount: str) -> bool:
    """True when parsed subtotal/tax exist and disagree with operator cash."""
    computed = _breakdown_total(row)
    paid = _money0(amount)
    if computed is None or paid is None:
        return False
    return abs(computed - paid) > Decimal("0.01")


def _apply_reviewed_corrections(
    planned: dict[str, str],
    *,
    ocr: Mapping[str, str],
    corrections: Mapping[str, str],
    ocr_text_sha256: str,
) -> None:
    if not corrections:
        return
    ocr_bits: list[str] = []
    for field in (
        "order_id",
        "description",
        "schedule_c_or_form",
        "payment_method",
        "vendor",
        "amount_usd",
    ):
        if field not in corrections:
            continue
        before = ocr.get(field) or ""
        after = corrections[field]
        if before != after:
            ocr_bits.append(f"{field}={before or '(none)'}")
        planned[field] = after
    extra: list[str] = []
    if ocr_bits:
        extra.append("ocr " + "; ".join(ocr_bits))
    if ocr_text_sha256:
        extra.append(f"ocr_sha256={ocr_text_sha256}")
    ocr_gap = (ocr.get("gap") or "").strip()
    if ocr_gap and any(key in corrections for key in ("vendor", "amount_usd")):
        extra.append(f"ocr_gap={ocr_gap}")
    if "amount_usd" in corrections:
        extra.append(
            "effective amount_usd "
            + corrections["amount_usd"]
            + "; raw printed_total "
            + (planned.get("printed_total") or "none")
            + " subtotal "
            + (planned.get("subtotal") or "none")
            + " tax "
            + (planned.get("tax") or "none")
            + " retained as OCR diagnostics"
        )
    provenance = corrections.get("review_provenance")
    if provenance:
        extra.append(f"review_provenance={provenance}")
    rationale = corrections.get("review_rationale")
    if rationale:
        extra.append(f"review_rationale={rationale}")
    purpose = corrections.get("purpose")
    if purpose:
        extra.append(f"operator: {purpose}")
    if extra:
        planned["notes"] = (
            planned["notes"] + " | " if planned["notes"] else ""
        ) + " | ".join(extra)
    _finalize_reviewed_status(planned, corrections)


def _finalize_reviewed_status(
    planned: dict[str, str], corrections: Mapping[str, str]
) -> None:
    vendor = (planned.get("vendor") or "").strip()
    amount = (planned.get("amount_usd") or "").strip()
    if vendor.casefold() == "unknown":
        if planned.get("status") == "DOCUMENTED":
            planned["status"] = "NEED_REVIEW"
        return
    if "amount_usd" in corrections and operator_amount_conflicts_breakdown(
        planned, corrections["amount_usd"]
    ):
        planned["status"] = "NEED_REVIEW"
        return
    if amount and (
        planned.get("status") == "DOCUMENTED"
        or "vendor" in corrections
        or "amount_usd" in corrections
    ):
        planned["status"] = "DOCUMENTED"


def _ingest_reason(
    *,
    corrections: Mapping[str, str],
    ocr: Mapping[str, str],
    override: str,
) -> str:
    if not corrections:
        return f"override: {override}" if override else "ingest"
    fields = [
        key
        for key in (
            "order_id",
            "description",
            "schedule_c_or_form",
            "payment_method",
            "vendor",
            "amount_usd",
        )
        if key in corrections
    ]
    parts = ["reviewed correction"]
    if fields:
        parts.append(", ".join(fields))
    purpose = corrections.get("purpose")
    if purpose:
        parts.append(f"operator: {purpose}")
    provenance = corrections.get("review_provenance")
    if provenance:
        parts.append(f"review_provenance={provenance}")
    rationale = corrections.get("review_rationale")
    if rationale:
        parts.append(f"review_rationale={rationale}")
    ocr_bits = []
    for field in fields:
        before = ocr.get(field) or ""
        if before != corrections[field]:
            ocr_bits.append(f"{field}={before or '(none)'}")
    if ocr_bits:
        parts.append("ocr " + "; ".join(ocr_bits))
    if override:
        parts.append(f"override: {override}")
    return "; ".join(parts)


def _cash_review_block(
    planned: Mapping[str, str],
    corrections: Mapping[str, str],
    override: str,
) -> str | None:
    """None if the planned snapshot may be written. Detail if it must stay blocked."""
    vendor = (planned.get("vendor") or "").strip()
    amount = (planned.get("amount_usd") or "").strip()
    status = (planned.get("status") or "").strip()
    operator_amount = corrections.get("amount_usd")
    mismatch, detail = totals_mismatch(planned)

    if vendor.casefold() == "unknown" and amount:
        return (
            "vendor unknown — reviewed vendor + review_provenance required; "
            "override_reason is not permission"
        )
    if status == "NEED_REVIEW" and not amount and not operator_amount:
        return (
            "uncorroborated cash — reviewed amount_usd + review_provenance "
            "required; override_reason is not permission"
        )
    if operator_amount and operator_amount_conflicts_breakdown(
        planned, operator_amount
    ):
        return (
            "operator amount_usd conflicts with parsed subtotal/tax; "
            "amount-only override cannot rewrite the raw breakdown. "
            "A coherent reviewed money breakdown is not supported in this "
            "path — pass amount_usd that matches subtotal+shipping+tax-discount, "
            "or leave the row blocked. Raw printed_total stays diagnostic."
        )
    if mismatch:
        if operator_amount and not operator_amount_conflicts_breakdown(
            planned, operator_amount
        ):
            return None
        if status == "DOCUMENTED" and amount and override:
            return None
        if status != "DOCUMENTED" or not amount:
            return (
                "mismatched or uncorroborated cash — reviewed amount_usd + "
                "review_provenance required; override_reason is not permission"
                + (f" ({detail})" if detail else "")
            )
        return detail
    return None


def _actionable_gap(
    planned: Mapping[str, str],
    parsed: ParsedRow,
    cash_block: str | None,
) -> str | None:
    """Current booking deficiency. Original OCR gap lives on ocr/ocr_gap."""
    if (planned.get("status") or "") == "DOCUMENTED":
        return None
    return cash_block or parsed.gap


def _token_mismatch(book: str, source_name: str, detail: str) -> IngestResult:
    return IngestResult(
        book=book,
        action="blocked",
        source_name=source_name,
        gap=detail,
        message=detail,
    )


def normalize_splits(raw: Sequence[Mapping[str, object]] | Sequence[SplitSpec]) -> list[SplitSpec]:
    """Jon-named line items. Two or more. Do not guess amounts."""
    if not raw:
        raise ValueError("splits must list each line: [{book, amount, description}, ...]")
    out: list[SplitSpec] = []
    for i, item in enumerate(raw):
        if isinstance(item, SplitSpec):
            book = item.book
            amount = item.amount_usd
            desc = item.description
        elif isinstance(item, Mapping):
            book = str(item.get("book") or "").strip().lower()
            amount = str(item.get("amount") or item.get("amount_usd") or "").strip()
            desc = str(item.get("description") or "").strip()
        else:
            raise ValueError(f"splits[{i}] must be an object with book and amount")
        from soveryn.platform.ledgers.registry import book_ids

        if book not in book_ids():
            raise ValueError(f"splits[{i}].book must be soveryn or cwg")
        cash = _money(amount)
        if cash is None:
            raise ValueError(f"splits[{i}].amount must be well-formed dollars (got {amount!r})")
        out.append(SplitSpec(book=book, amount_usd=cash, description=desc))
    if len(out) < 2:
        raise ValueError("splits need at least two lines (one receipt, two books or two items)")
    return out


def _money(raw: str) -> str | None:
    cleaned = (raw or "").strip().replace("$", "").replace(",", "")
    try:
        value = Decimal(cleaned)
    except (InvalidOperation, AttributeError):
        return None
    if value <= 0:
        return None
    return f"{value.quantize(Decimal('0.01'))}"


def _money0(raw: str) -> Decimal | None:
    cleaned = (raw or "").strip().replace("$", "").replace(",", "")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, AttributeError):
        return None


def totals_mismatch(row: Mapping[str, str]) -> tuple[bool, str]:
    """True when subtotal + shipping + tax − discount misses printed_total by >1¢."""
    printed = _money0(row.get("printed_total") or "")
    subtotal = _money0(row.get("subtotal") or "")
    if printed is None or subtotal is None:
        return False, ""
    shipping = _money0(row.get("shipping") or "") or Decimal("0.00")
    tax = _money0(row.get("tax") or "") or Decimal("0.00")
    discount = _money0(row.get("discount") or "") or Decimal("0.00")
    computed = (subtotal + shipping + tax - discount).quantize(Decimal("0.01"))
    printed_q = printed.quantize(Decimal("0.01"))
    if abs(computed - printed_q) <= Decimal("0.01"):
        return False, ""
    detail = (
        f"subtotal {subtotal} + shipping {shipping} + tax {tax} "
        f"- discount {discount} = {computed} != printed_total {printed_q}"
    )
    return True, detail


def _purge_confirm() -> None:
    now = time.time()
    expired = [key for key, item in _CONFIRM.items() if float(item["expires_at"]) <= now]
    for key in expired:
        _CONFIRM.pop(key, None)


def issue_confirm_token(payload: Mapping[str, Any], *, ttl: int = CONFIRM_TTL_SECONDS) -> tuple[str, float]:
    token = secrets.token_urlsafe(24)
    expires = time.time() + ttl
    with _CONFIRM_LOCK:
        _purge_confirm()
        _CONFIRM[token] = {"expires_at": expires, "payload": dict(payload)}
    return token, expires


def peek_confirm_token(token: str) -> dict[str, Any] | None:
    with _CONFIRM_LOCK:
        _purge_confirm()
        item = _CONFIRM.get(token)
        if item is None:
            return None
        return dict(item["payload"])


def consume_confirm_token(token: str) -> dict[str, Any] | None:
    with _CONFIRM_LOCK:
        _purge_confirm()
        item = _CONFIRM.pop(token, None)
        if item is None:
            return None
        return dict(item["payload"])


def _blank_row() -> dict[str, str]:
    return {k: "" for k in CSV_FIELDS}


def _csv_from_parsed(parsed: ParsedRow) -> dict[str, str]:
    row = _blank_row()
    row.update(parsed.as_csv())
    if not row.get("row_id"):
        row["row_id"] = parsed.row_id or new_row_id()
    return row


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _already_filed(
    path: Path, rows: list[dict[str, str]], dest_root: Path
) -> dict[str, str] | None:
    """Existing row whose filed file is byte-identical to path."""
    if not path.is_file():
        return None
    size = path.stat().st_size
    digest: str | None = None
    for row in rows:
        rel = (row.get("evidence") or "").strip()
        if not rel.startswith("evidence/"):
            continue
        cand = dest_root / rel[len("evidence/") :]
        if not cand.is_file() or cand.stat().st_size != size:
            continue
        digest = digest or _sha256(path)
        if _sha256(cand) == digest:
            return dict(row)
    return None


def _duplicate_of(
    *,
    rows: list[dict[str, str]],
    parsed: ParsedRow,
    source: Path | None,
    ev_root: Path | None,
    digest: str = "",
) -> dict[str, str] | None:
    hit = find_duplicate(
        rows,
        row_id=parsed.row_id,
        evidence_sha256=digest or parsed.evidence_sha256,
        order_id=parsed.order_id or "",
    )
    if hit is not None:
        return hit
    if source is not None and ev_root is not None:
        return _already_filed(source, rows, ev_root)
    return None


def _exists_result(
    book: str,
    source_name: str,
    parsed: ParsedRow,
    existing: Mapping[str, str],
) -> IngestResult:
    return IngestResult(
        book=book,
        action="duplicate",
        source_name=source_name,
        order_id=parsed.order_id or existing.get("order_id") or None,
        amount_usd=existing.get("amount_usd") or parsed.amount_usd,
        evidence=existing.get("evidence") or parsed.evidence or None,
        message=f"already on the {book} book",
        row=dict(existing),
        rows=[dict(existing)],
    )


def _preview_result(
    book: str,
    source_name: str,
    parsed: ParsedRow,
    planned: Sequence[Mapping[str, str]],
    *,
    payload: Mapping[str, Any],
    message: str,
    splits: list[dict[str, str]] | None = None,
    ocr: Mapping[str, str] | None = None,
    corrections: Mapping[str, str] | None = None,
    gap: str | None = None,
) -> IngestResult:
    token, expires = issue_confirm_token(payload)
    planned0 = planned[0] if planned else None
    return IngestResult(
        book=book,
        action="preview",
        source_name=source_name,
        order_id=(planned0.get("order_id") if planned0 else None) or parsed.order_id,
        amount_usd=(planned0.get("amount_usd") if planned0 else None) or parsed.amount_usd,
        evidence=planned0.get("evidence") if planned0 else parsed.evidence or None,
        gap=gap,
        message=message,
        splits=list(splits or []),
        rows=[dict(r) for r in planned],
        row=dict(planned0) if planned0 is not None and len(planned) == 1 else None,
        confirm_token=token,
        confirm_expires_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires)),
        ocr=dict(ocr) if ocr is not None else None,
        ocr_gap=parsed.gap,
        corrections=dict(corrections) if corrections else None,
    )


def _blocked_result(
    book: str,
    source_name: str,
    parsed: ParsedRow,
    planned: Sequence[Mapping[str, str]],
    detail: str,
    *,
    message: str | None = None,
    ocr: Mapping[str, str] | None = None,
    corrections: Mapping[str, str] | None = None,
) -> IngestResult:
    planned0 = planned[0] if planned else None
    return IngestResult(
        book=book,
        action="blocked",
        source_name=source_name,
        order_id=(planned0.get("order_id") if planned0 else None) or parsed.order_id,
        amount_usd=(
            (planned0.get("amount_usd") if planned0 else None) or parsed.amount_usd
        ),
        gap=detail,
        message=message
        or (
            "totals do not match within a cent — pass override_reason to book anyway"
        ),
        rows=[dict(r) for r in planned],
        row=dict(planned0) if planned0 is not None else None,
        ocr=dict(ocr) if ocr is not None else None,
        ocr_gap=parsed.gap,
        corrections=dict(corrections) if corrections else None,
    )


def ingest_path(
    path: Path,
    *,
    books: Mapping[str, Path] | None = None,
    evidence_roots: Mapping[str, Path] | None = None,
    extract: ExtractFn | None = None,
    folder_hint: str | None = None,
    book: str | None = None,
    splits: Sequence[Mapping[str, object]] | Sequence[SplitSpec] | None = None,
    confirm: bool = True,
    confirm_token: str | None = None,
    override_reason: str | None = None,
    corrections: Mapping[str, object] | None = None,
    actor: str = "ledger_ingest",
) -> IngestResult:
    """Copy evidence and append when confirm is true.

    Chat photo hooks and ledger_ingest tool previews must pass confirm=False.
    A write from the tool requires the confirm_token issued by that preview.
    Default confirm=True is for explicit CLI/library callers only.
    Reviewed corrections (invoice/description/category/payment/purpose/vendor/
    amount_usd plus review provenance) bind into the preview token; changing
    them, the review reason, the book, or the file invalidates it.
    """
    path = Path(path)
    extract_fn = extract or extract_receipt_path
    house_defaults = books is None
    book_paths = books if books is not None else _registered_book_paths()
    ev_roots = evidence_roots if evidence_roots is not None else _registered_evidence_roots()
    override = (override_reason or "").strip()
    caller_corrections: dict[str, str] | None
    if corrections is None:
        caller_corrections = None
    else:
        caller_corrections = normalize_corrections(corrections)
    if actor == "chat_receipt_preview":
        # Chat uploads never book, even if a caller passes confirm=True.
        confirm = False
        confirm_token = None

    bound_sha = None
    bound_book = None
    bound_corrections: dict[str, str] | None = None
    bound_semantic: dict[str, str] | None = None
    bound_override: str | None = None
    bound_ocr_money: dict[str, str] | None = None
    applied_corrections: dict[str, str] = caller_corrections or {}
    if confirm_token:
        payload = consume_confirm_token(confirm_token)
        if payload is None:
            return IngestResult(
                book="unsorted",
                action="blocked",
                source_name=path.name,
                gap="confirm token is missing or expired — preview again",
                message="confirm token is missing or expired",
            )
        if payload.get("source") == "chat_preview":
            return _token_mismatch(
                str(payload.get("book") or "unsorted"),
                path.name,
                "chat preview token cannot book — preview again with "
                "ledger_ingest and reviewed corrections if OCR fields are wrong",
            )
        confirm = True
        bound_sha = payload.get("source_sha256")
        bound_book = payload.get("book")
        token_corr = payload.get("corrections")
        if isinstance(token_corr, Mapping):
            bound_corrections = normalize_corrections(token_corr)
        token_sem = payload.get("semantic")
        if isinstance(token_sem, Mapping):
            bound_semantic = {str(k): str(v) for k, v in token_sem.items()}
        token_override = payload.get("override_reason")
        if isinstance(token_override, str):
            bound_override = token_override
        token_ocr_money = payload.get("ocr_money")
        if isinstance(token_ocr_money, Mapping):
            bound_ocr_money = {str(k): str(v) for k, v in token_ocr_money.items()}
        if bound_override is not None and override != bound_override:
            return _token_mismatch(
                str(bound_book or "unsorted"),
                path.name,
                "confirm token does not match this override_reason",
            )
        if bound_override is not None:
            override = bound_override
        if caller_corrections is not None:
            if bound_corrections is None:
                if caller_corrections:
                    return _token_mismatch(
                        str(bound_book or "unsorted"),
                        path.name,
                        "confirm token does not match these corrections",
                    )
            elif caller_corrections != bound_corrections:
                return _token_mismatch(
                    str(bound_book or "unsorted"),
                    path.name,
                    "confirm token does not match these corrections",
                )
            applied_corrections = caller_corrections
        elif bound_corrections is not None:
            applied_corrections = bound_corrections
        if (
            isinstance(bound_sha, str)
            and bound_sha
            and path.is_file()
            and _sha256(path) != bound_sha
        ):
            return _token_mismatch(
                str(bound_book or "unsorted"),
                path.name,
                "confirm token does not match this receipt",
            )

    if splits and applied_corrections:
        raise ValueError("corrections apply to a single receipt preview, not splits")

    extracted = extract_fn(path)
    text = extracted.text or ""
    hit = classify_receipt(path.name, text)
    parsed = parse_receipt(text, source_name=path.name)
    extra_notes: list[str] = []
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}:
        extra_notes.append("photo receipt")
        if extracted.gap:
            extra_notes.append(extracted.gap)
    if parsed.gap and parsed.status == "DOCUMENTED":
        extra_notes.append(parsed.gap)
    if extra_notes:
        parsed.notes = (parsed.notes + " | " if parsed.notes else "") + " | ".join(
            extra_notes
        )
    if path.is_file():
        parsed.evidence_sha256 = _sha256(path)
    ocr = _ocr_fields(parsed)
    ocr_text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ocr_money = _ocr_money_fields(parsed)
    if bound_ocr_money is not None and ocr_money != bound_ocr_money:
        return _token_mismatch(
            str(bound_book or "unsorted"),
            path.name,
            "confirm token does not match the parsed OCR money snapshot",
        )

    if splits:
        specs = normalize_splits(splits)
        return _apply_splits(
            parsed,
            specs,
            source_path=path,
            source_name=path.name,
            book_paths=book_paths,
            ev_roots=ev_roots,
            confirm=confirm,
            override_reason=override,
            actor=actor,
        )

    forced = (book or "").strip().lower() or None
    from soveryn.platform.ledgers.registry import book_ids

    known = book_ids()
    if forced in known:
        routed = forced
    else:
        routed = hit.book
        hint = (folder_hint or path.parent.name or "").lower()
        if hint in known:
            if routed == "unsorted":
                routed = hint
            elif routed != hint:
                return IngestResult(
                    book="unsorted",
                    action="unsorted",
                    source_name=path.name,
                    gap=f"folder is {hint} but body classifies as {hit.book} — do not guess",
                    message="left unsorted",
                )
    book = routed
    if (
        isinstance(bound_book, str)
        and bound_book
        and bound_book not in {"unsorted", "split"}
        and book != bound_book
    ):
        return IngestResult(
            book=book,
            action="blocked",
            source_name=path.name,
            gap="confirm token does not match this book",
            message="confirm token does not match this book",
        )

    if book == "unsorted":
        # Preview must not copy into intake. Booking still parks unsure files.
        if confirm and house_defaults and path.is_file():
            hold = ensure_drop_dirs() / "unsorted"
            hold.mkdir(parents=True, exist_ok=True)
            if path.parent.resolve() != hold.resolve():
                dest = hold / path.name
                if dest.exists():
                    dest = hold / (path.stem + "-2" + path.suffix)
                shutil.copy2(path, dest)
        return IngestResult(
            book="unsorted",
            action="unsorted",
            source_name=path.name,
            order_id=parsed.order_id,
            amount_usd=parsed.amount_usd,
            gap=hit.gap or parsed.gap or extracted.gap,
            message=hit.gap or "unsorted — say SOVERYN or CWG, or pass splits",
        )

    csv_path = book_paths[book]
    ev_root = Path(ev_roots[book])
    planned = _csv_from_parsed(parsed)
    planned["evidence_sha256"] = parsed.evidence_sha256
    planned["order_id"] = parsed.order_id or ""
    _apply_reviewed_corrections(
        planned,
        ocr=ocr,
        corrections=applied_corrections,
        ocr_text_sha256=ocr_text_sha256,
    )
    named = replace(
        parsed,
        vendor=planned.get("vendor") or parsed.vendor,
        amount_usd=planned.get("amount_usd") or parsed.amount_usd,
        description=planned.get("description") or parsed.description,
    )
    planned["evidence"] = _planned_evidence_rel(path, named, ev_root)
    semantic = _semantic_fields(planned)
    if bound_semantic is not None and semantic != bound_semantic:
        return _token_mismatch(
            book,
            path.name,
            "confirm token does not match the reviewed fields",
        )
    cash_block = _cash_review_block(planned, applied_corrections, override)

    other = next((bid for bid in book_paths if bid != book), None)
    other_csv = book_paths.get(other) if other else None
    split_ids = {oid for oid in (parsed.order_id, planned.get("order_id")) if oid}
    if other_csv is not None:
        other_rows = load_rows(other_csv)
        for oid in split_ids:
            if has_order_id(other_rows, oid):
                return IngestResult(
                    book="unsorted",
                    action="needs_split",
                    source_name=path.name,
                    order_id=oid,
                    amount_usd=parsed.amount_usd,
                    gap=(
                        f"order {oid} already on the {other} book — "
                        "do not file the full total on both. Pass splits."
                    ),
                    message="needs split across books",
                    ocr=ocr,
                    corrections=applied_corrections or None,
                )

    existing = load_rows(csv_path)
    found = _duplicate_of(
        rows=existing,
        parsed=parsed,
        source=path,
        ev_root=ev_root,
        digest=parsed.evidence_sha256,
    )
    if found is None and planned.get("order_id"):
        found = find_duplicate(existing, order_id=planned["order_id"])
    if found is not None:
        return _exists_result(book, path.name, parsed, found)

    if not confirm:
        payload = {
            "kind": "ingest_path",
            "path": str(path),
            "book": book,
            "folder_hint": folder_hint,
            "override_reason": override,
            "source_sha256": _sha256(path) if path.is_file() else "",
            "corrections": applied_corrections,
            "semantic": semantic,
            "ocr_money": ocr_money,
            "source": (
                "chat_preview" if actor == "chat_receipt_preview" else "ledger_ingest"
            ),
            "ocr_text_sha256": ocr_text_sha256,
        }
        reviewed = " with reviewed corrections" if applied_corrections else ""
        status = planned.get("status") or parsed.status
        return _preview_result(
            book,
            path.name,
            parsed,
            [planned],
            payload=payload,
            message=(
                f"preview {planned['amount_usd'] or 'NO AMOUNT'} {status} on {book}"
                f"{reviewed} — call again with confirm=true"
            ),
            ocr=ocr,
            corrections=applied_corrections,
            gap=_actionable_gap(planned, parsed, cash_block),
        )

    if cash_block:
        apex_style = (
            planned.get("status") == "DOCUMENTED"
            and bool(planned.get("amount_usd"))
            and "amount_usd" not in applied_corrections
        )
        return _blocked_result(
            book,
            path.name,
            parsed,
            [planned],
            cash_block,
            message=(
                "totals do not match within a cent — pass override_reason to book anyway"
                if apex_style
                else cash_block
            ),
            ocr=ocr,
            corrections=applied_corrections,
        )

    with exclusive_book(csv_path):
        existing = load_rows(csv_path)
        found = _duplicate_of(
            rows=existing,
            parsed=parsed,
            source=path,
            ev_root=ev_root,
            digest=parsed.evidence_sha256,
        )
        if found is None and planned.get("order_id"):
            found = find_duplicate(existing, order_id=planned["order_id"])
        if found is not None:
            return _exists_result(book, path.name, parsed, found)
        named = replace(
            parsed,
            vendor=planned.get("vendor") or parsed.vendor,
            amount_usd=planned.get("amount_usd") or parsed.amount_usd,
            description=planned.get("description") or parsed.description,
        )
        rel_evidence = _place_evidence(path, named, ev_root)
        parsed.evidence = rel_evidence
        planned["evidence"] = rel_evidence
        reason = _ingest_reason(
            corrections=applied_corrections, ocr=ocr, override=override
        )
        written = write_book(
            csv_path,
            existing + [planned],
            actor=actor,
            changes=[
                ChangeRecord(
                    action="append",
                    row_id=planned.get("row_id", ""),
                    before=None,
                    after=planned,
                    reason=reason,
                )
            ],
            reason=reason,
            already_locked=True,
        )[-1]
    return IngestResult(
        book=book,
        action="appended",
        source_name=path.name,
        order_id=written.get("order_id") or parsed.order_id,
        amount_usd=written.get("amount_usd") or parsed.amount_usd,
        evidence=rel_evidence,
        gap=_actionable_gap(planned, parsed, None),
        message=f"appended {written.get('amount_usd') or 'NO AMOUNT'} to {book}",
        row=written,
        rows=[written],
        ocr=ocr,
        ocr_gap=parsed.gap,
        corrections=applied_corrections or None,
    )


def split_existing_order(
    order_id: str,
    splits: Sequence[Mapping[str, object]] | Sequence[SplitSpec],
    *,
    books: Mapping[str, Path] | None = None,
    evidence_roots: Mapping[str, Path] | None = None,
    confirm: bool = True,
    override_reason: str | None = None,
    actor: str = "ledger_ingest",
) -> IngestResult:
    """Replace a full-amount duplicate with Jon's line split. Same receipt, two books."""
    oid = (order_id or "").strip()
    if not oid:
        raise ValueError("order_id is required to split an already-filed receipt")
    specs = normalize_splits(splits)
    book_paths = books if books is not None else _registered_book_paths()
    ev_roots = evidence_roots if evidence_roots is not None else _registered_evidence_roots()
    template: dict[str, str] | None = None
    for csv_path in book_paths.values():
        hits = rows_for_order(load_rows(csv_path), oid)
        if hits:
            template = hits[0]
            break
    if template is None:
        return IngestResult(
            book="unsorted",
            action="missing",
            source_name="",
            order_id=oid,
            gap="order is not on either book — pass path to the receipt",
            message="order not found",
        )
    parsed = ParsedRow(
        tax_year=template.get("tax_year", ""),
        date=template.get("date", ""),
        vendor=template.get("vendor", ""),
        description=template.get("description", ""),
        schedule_c_or_form=template.get("schedule_c_or_form", ""),
        amount_usd=template.get("amount_usd", ""),
        status=template.get("status", "DOCUMENTED"),
        payment_method=template.get("payment_method", ""),
        evidence=template.get("evidence", ""),
        notes=template.get("notes", ""),
        order_id=oid,
        subtotal=template.get("subtotal", ""),
        shipping=template.get("shipping", ""),
        tax=template.get("tax", ""),
        discount=template.get("discount", ""),
        printed_total=template.get("printed_total", ""),
        evidence_sha256=template.get("evidence_sha256", ""),
    )
    return _apply_splits(
        parsed,
        specs,
        source_path=None,
        source_name=Path(template.get("evidence") or "").name or oid,
        book_paths=book_paths,
        ev_roots=ev_roots,
        confirm=confirm,
        override_reason=override_reason or "",
        actor=actor,
    )


def _apply_splits(
    parsed: ParsedRow,
    specs: list[SplitSpec],
    *,
    source_path: Path | None,
    source_name: str,
    book_paths: Mapping[str, Path],
    ev_roots: Mapping[str, Path],
    confirm: bool = True,
    override_reason: str = "",
    actor: str = "ledger_ingest",
) -> IngestResult:
    oid = parsed.order_id or ""
    if not oid:
        return IngestResult(
            book="unsorted",
            action="unsorted",
            source_name=source_name,
            amount_usd=parsed.amount_usd,
            gap="cannot split a receipt with no order id — do not guess",
            message="no order id",
        )

    digest = parsed.evidence_sha256
    if source_path is not None and source_path.is_file() and not digest:
        digest = _sha256(source_path)

    planned: list[dict[str, str]] = []
    preview_splits: list[dict[str, str]] = []
    for spec in specs:
        line = _split_row(parsed, spec)
        line["order_id"] = oid
        line["evidence_sha256"] = digest
        line["row_id"] = new_row_id()
        if source_path is not None and source_path.is_file():
            line_parsed = replace(
                parsed,
                amount_usd=spec.amount_usd,
                description=line["description"],
            )
            line["evidence"] = _planned_evidence_rel(
                source_path, line_parsed, Path(ev_roots[spec.book])
            )
        elif parsed.evidence:
            line["evidence"] = parsed.evidence
        planned.append(line)
        preview_splits.append(
            {
                "book": spec.book,
                "amount_usd": spec.amount_usd,
                "description": line["description"],
                "evidence": line.get("evidence", ""),
                "row_id": line["row_id"],
            }
        )

    for line in planned:
        mismatch, detail = totals_mismatch(line)
        if mismatch and not override_reason:
            return _blocked_result("split", source_name, parsed, planned, detail)

    if not confirm:
        return _preview_result(
            "split",
            source_name,
            parsed,
            planned,
            payload={
                "kind": "split",
                "order_id": oid,
                "source_name": source_name,
            },
            message=f"preview split of order {oid} — call again with confirm=true",
            splits=preview_splits,
        )

    for book, csv_path in sorted(book_paths.items(), key=lambda item: item[0]):
        with exclusive_book(csv_path):
            existing = load_rows(csv_path)
            removed = rows_for_order(existing, oid)
            kept = without_order(existing, oid)
            added = []
            for spec, line in zip(specs, planned, strict=True):
                if spec.book != book:
                    continue
                if source_path is not None and source_path.is_file():
                    line_parsed = replace(
                        parsed,
                        amount_usd=spec.amount_usd,
                        description=line["description"],
                    )
                    line["evidence"] = _place_evidence(
                        source_path, line_parsed, Path(ev_roots[spec.book])
                    )
                elif parsed.evidence:
                    line["evidence"] = parsed.evidence
                added.append(line)
            if not removed and not added:
                continue
            changes = [
                ChangeRecord(
                    action="remove",
                    row_id=row.get("row_id", ""),
                    before=row,
                    after=None,
                    reason=f"split order {oid}",
                )
                for row in removed
            ]
            changes.extend(
                ChangeRecord(
                    action="append",
                    row_id=row.get("row_id", ""),
                    before=None,
                    after=row,
                    reason=override_reason or f"split order {oid}",
                )
                for row in added
            )
            write_book(
                csv_path,
                kept + added,
                actor=actor,
                changes=changes,
                reason=override_reason or f"split order {oid}",
                already_locked=True,
            )

    amounts = " + ".join(f"{w['book']} {w['amount_usd']}" for w in preview_splits)
    return IngestResult(
        book="split",
        action="split",
        source_name=source_name,
        order_id=oid,
        amount_usd=parsed.amount_usd,
        splits=preview_splits,
        rows=planned,
        message=f"split order {oid}: {amounts}",
    )


def _split_row(parsed: ParsedRow, spec: SplitSpec) -> dict[str, str]:
    desc = spec.description or parsed.description
    oid = parsed.order_id or ""
    if oid and oid not in desc:
        desc = f"{desc} (order {oid})"
    receipt_cash = parsed.amount_usd
    note_bits = [f"split line {spec.amount_usd} of order {oid}"]
    if receipt_cash:
        note_bits.append(f"receipt cash {receipt_cash}")
    if parsed.notes:
        note_bits.append(parsed.notes)
    row = _blank_row()
    row.update(
        {
            "tax_year": parsed.tax_year,
            "date": parsed.date,
            "vendor": parsed.vendor,
            "description": desc[:200],
            "schedule_c_or_form": schedule_for("", desc, parsed.vendor),
            "amount_usd": spec.amount_usd,
            "status": "DOCUMENTED" if spec.amount_usd else parsed.status,
            "payment_method": parsed.payment_method,
            "evidence": parsed.evidence,
            "notes": " | ".join(note_bits),
            "order_id": oid,
            "subtotal": parsed.subtotal,
            "shipping": parsed.shipping,
            "tax": parsed.tax,
            "discount": parsed.discount or parsed.rewards,
            "printed_total": parsed.printed_total,
            "evidence_sha256": parsed.evidence_sha256,
        }
    )
    return row


def _planned_evidence_rel(path: Path, parsed: ParsedRow, dest_root: Path) -> str:
    year = parsed.date[:4] if parsed.date else "undated"
    dest_dir = dest_root / year
    dest = dest_dir / _evidence_name(parsed, path)
    if dest.exists() and dest.resolve() != path.resolve():
        dest = dest_dir / (dest.stem + "-2" + dest.suffix)
    return f"evidence/{year}/{dest.name}"


def _place_evidence(path: Path, parsed: ParsedRow, dest_root: Path) -> str:
    year = parsed.date[:4] if parsed.date else "undated"
    dest_dir = dest_root / year
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _evidence_name(parsed, path)
    if dest.exists() and dest.resolve() != path.resolve():
        dest = dest_dir / (dest.stem + "-2" + dest.suffix)
    if path.resolve() != dest.resolve():
        shutil.copy2(path, dest)
    return f"evidence/{year}/{dest.name}"


def ingest_drop(
    drop: Path | None = None,
    *,
    files: Sequence[Path] | None = None,
    books: Mapping[str, Path] | None = None,
    evidence_roots: Mapping[str, Path] | None = None,
    extract: ExtractFn | None = None,
    confirm: bool = True,
    override_reason: str | None = None,
) -> list[IngestResult]:
    """Ingest named files only. Folder-wide walks are refused."""
    if not files:
        raise ValueError(FOLDER_WIDE_REFUSED)
    results: list[IngestResult] = []
    for receipt in files:
        receipt = Path(receipt)
        hint = receipt.parent.name if receipt.parent.name != "unsorted" else None
        results.append(
            ingest_path(
                receipt,
                books=books,
                evidence_roots=evidence_roots,
                extract=extract,
                folder_hint=hint,
                confirm=confirm,
                override_reason=override_reason,
            )
        )
    return results


def _evidence_name(parsed, path: Path) -> str:
    date = parsed.date or "undated"
    vendor = _slug(parsed.vendor)[:24] or "vendor"
    desc = _slug(parsed.description)[:40] or path.stem[:40]
    amount = parsed.amount_usd or "na"
    suffix = path.suffix.lower() or ".pdf"
    return f"{date}_{vendor}_{desc}_{amount}{suffix}"


def _slug(raw: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", raw).strip("-").lower()
    return cleaned
