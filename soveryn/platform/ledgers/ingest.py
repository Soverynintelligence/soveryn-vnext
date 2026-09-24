"""Copy evidence and append to the matching book. Unsorted when unsure."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import shutil
from typing import Callable, Mapping, Sequence

from soveryn.platform.intake.pdf import ExtractResult
from soveryn.platform.ledgers.books import (
    append_row,
    has_order_id,
    load_rows,
    rows_for_order,
    without_order,
    write_rows,
)
from soveryn.platform.ledgers.classify import classify_receipt
from soveryn.platform.ledgers.extract import RECEIPT_SUFFIXES, extract_receipt_path
from soveryn.platform.ledgers.parse import ParsedRow, parse_receipt
from soveryn.platform.ledgers.parse import _schedule as schedule_for
from soveryn.platform.ledgers.paths import (
    cwg_csv,
    ensure_drop_dirs,
    evidence_root as default_evidence_root,
    soveryn_csv,
)

ExtractFn = Callable[[Path], ExtractResult]


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

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


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
        if book not in {"soveryn", "cwg"}:
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


def ingest_path(
    path: Path,
    *,
    books: Mapping[str, Path] | None = None,
    evidence_roots: Mapping[str, Path] | None = None,
    extract: ExtractFn | None = None,
    folder_hint: str | None = None,
    book: str | None = None,
    splits: Sequence[Mapping[str, object]] | Sequence[SplitSpec] | None = None,
) -> IngestResult:
    path = Path(path)
    extract_fn = extract or extract_receipt_path
    house_defaults = books is None
    book_paths = books or {
        "soveryn": soveryn_csv(),
        "cwg": cwg_csv(),
    }
    ev_roots = evidence_roots or {
        "soveryn": default_evidence_root("soveryn"),
        "cwg": default_evidence_root("cwg"),
    }

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

    if splits:
        specs = normalize_splits(splits)
        return _apply_splits(
            parsed,
            specs,
            source_path=path,
            source_name=path.name,
            book_paths=book_paths,
            ev_roots=ev_roots,
        )

    forced = (book or "").strip().lower() or None
    if forced in {"soveryn", "cwg"}:
        routed = forced
    else:
        routed = hit.book
        hint = (folder_hint or path.parent.name or "").lower()
        if hint in {"soveryn", "cwg"}:
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

    if book == "unsorted":
        if house_defaults and path.is_file():
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
    existing = load_rows(csv_path)
    if parsed.order_id and has_order_id(existing, parsed.order_id):
        return IngestResult(
            book=book,
            action="duplicate",
            source_name=path.name,
            order_id=parsed.order_id,
            amount_usd=parsed.amount_usd,
            message=f"order {parsed.order_id} already on the {book} book",
        )

    other = "cwg" if book == "soveryn" else "soveryn"
    other_csv = book_paths.get(other)
    if parsed.order_id and other_csv is not None and has_order_id(load_rows(other_csv), parsed.order_id):
        return IngestResult(
            book="unsorted",
            action="needs_split",
            source_name=path.name,
            order_id=parsed.order_id,
            amount_usd=parsed.amount_usd,
            gap=(
                f"order {parsed.order_id} already on the {other} book — "
                "do not file the full total on both. Pass splits."
            ),
            message="needs split across books",
        )

    rel_evidence = _place_evidence(path, parsed, Path(ev_roots[book]))
    parsed.evidence = rel_evidence
    append_row(csv_path, parsed.as_csv())
    return IngestResult(
        book=book,
        action="appended",
        source_name=path.name,
        order_id=parsed.order_id,
        amount_usd=parsed.amount_usd,
        evidence=rel_evidence,
        gap=parsed.gap,
        message=f"appended {parsed.amount_usd or 'NO AMOUNT'} to {book}",
    )


def split_existing_order(
    order_id: str,
    splits: Sequence[Mapping[str, object]] | Sequence[SplitSpec],
    *,
    books: Mapping[str, Path] | None = None,
    evidence_roots: Mapping[str, Path] | None = None,
) -> IngestResult:
    """Replace a full-amount duplicate with Jon's line split. Same receipt, two books."""
    oid = (order_id or "").strip()
    if not oid:
        raise ValueError("order_id is required to split an already-filed receipt")
    specs = normalize_splits(splits)
    book_paths = books or {
        "soveryn": soveryn_csv(),
        "cwg": cwg_csv(),
    }
    ev_roots = evidence_roots or {
        "soveryn": default_evidence_root("soveryn"),
        "cwg": default_evidence_root("cwg"),
    }
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
    )
    return _apply_splits(
        parsed,
        specs,
        source_path=None,
        source_name=Path(template.get("evidence") or "").name or oid,
        book_paths=book_paths,
        ev_roots=ev_roots,
    )


def _apply_splits(
    parsed: ParsedRow,
    specs: list[SplitSpec],
    *,
    source_path: Path | None,
    source_name: str,
    book_paths: Mapping[str, Path],
    ev_roots: Mapping[str, Path],
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

    for book in ("soveryn", "cwg"):
        csv_path = book_paths[book]
        existing = load_rows(csv_path)
        kept = without_order(existing, oid)
        if len(kept) != len(existing):
            write_rows(csv_path, kept)

    written: list[dict[str, str]] = []
    for spec in specs:
        line = _split_row(parsed, spec)
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
        append_row(book_paths[spec.book], line)
        written.append(
            {
                "book": spec.book,
                "amount_usd": spec.amount_usd,
                "description": line["description"],
                "evidence": line.get("evidence", ""),
            }
        )

    amounts = " + ".join(f"{w['book']} {w['amount_usd']}" for w in written)
    return IngestResult(
        book="split",
        action="split",
        source_name=source_name,
        order_id=oid,
        amount_usd=parsed.amount_usd,
        splits=written,
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
    return {
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
    }


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
    books: Mapping[str, Path] | None = None,
    evidence_roots: Mapping[str, Path] | None = None,
    extract: ExtractFn | None = None,
) -> list[IngestResult]:
    if drop is None:
        root = ensure_drop_dirs()
    else:
        root = Path(drop)
        for name in ("soveryn", "cwg", "unsorted"):
            (root / name).mkdir(parents=True, exist_ok=True)

    results: list[IngestResult] = []
    for folder in ("soveryn", "cwg", "unsorted"):
        folder_path = root / folder
        if not folder_path.is_dir():
            continue
        files: list[Path] = []
        for path in sorted(folder_path.iterdir()):
            if path.is_file() and path.suffix.lower() in RECEIPT_SUFFIXES:
                files.append(path)
        for receipt in files:
            results.append(
                ingest_path(
                    receipt,
                    books=books,
                    evidence_roots=evidence_roots,
                    extract=extract,
                    folder_hint=folder if folder != "unsorted" else None,
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
