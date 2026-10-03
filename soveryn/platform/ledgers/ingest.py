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
) -> IngestResult:
    token, expires = issue_confirm_token(payload)
    return IngestResult(
        book=book,
        action="preview",
        source_name=source_name,
        order_id=parsed.order_id,
        amount_usd=parsed.amount_usd,
        evidence=planned[0].get("evidence") if planned else parsed.evidence or None,
        message=message,
        splits=list(splits or []),
        rows=[dict(r) for r in planned],
        row=dict(planned[0]) if len(planned) == 1 else None,
        confirm_token=token,
        confirm_expires_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires)),
    )


def _blocked_result(
    book: str,
    source_name: str,
    parsed: ParsedRow,
    planned: Sequence[Mapping[str, str]],
    detail: str,
) -> IngestResult:
    return IngestResult(
        book=book,
        action="blocked",
        source_name=source_name,
        order_id=parsed.order_id,
        amount_usd=parsed.amount_usd,
        gap=detail,
        message=(
            "totals do not match within a cent — pass override_reason to book anyway"
        ),
        rows=[dict(r) for r in planned],
        row=dict(planned[0]) if planned else None,
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
    actor: str = "ledger_ingest",
) -> IngestResult:
    path = Path(path)
    extract_fn = extract or extract_receipt_path
    house_defaults = books is None
    book_paths = books if books is not None else _registered_book_paths()
    ev_roots = evidence_roots if evidence_roots is not None else _registered_evidence_roots()
    override = (override_reason or "").strip()

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
        confirm = True

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
    ev_root = Path(ev_roots[book])
    other = next((bid for bid in book_paths if bid != book), None)
    other_csv = book_paths.get(other) if other else None
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

    existing = load_rows(csv_path)
    found = _duplicate_of(
        rows=existing,
        parsed=parsed,
        source=path,
        ev_root=ev_root,
        digest=parsed.evidence_sha256,
    )
    if found is not None:
        return _exists_result(book, path.name, parsed, found)

    planned = _csv_from_parsed(parsed)
    planned["evidence"] = _planned_evidence_rel(path, parsed, ev_root)
    planned["evidence_sha256"] = parsed.evidence_sha256
    planned["order_id"] = parsed.order_id or ""
    mismatch, detail = totals_mismatch(planned)
    if mismatch and not override:
        return _blocked_result(book, path.name, parsed, [planned], detail)

    if not confirm:
        payload = {
            "kind": "ingest_path",
            "path": str(path),
            "book": book,
            "folder_hint": folder_hint,
            "override_reason": override,
        }
        return _preview_result(
            book,
            path.name,
            parsed,
            [planned],
            payload=payload,
            message=f"preview {planned['amount_usd'] or 'NO AMOUNT'} on {book} — call again with confirm=true",
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
        if found is not None:
            return _exists_result(book, path.name, parsed, found)
        rel_evidence = _place_evidence(path, parsed, ev_root)
        parsed.evidence = rel_evidence
        planned["evidence"] = rel_evidence
        reason = "ingest"
        if override:
            reason = f"override: {override}"
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
        order_id=parsed.order_id,
        amount_usd=written.get("amount_usd") or parsed.amount_usd,
        evidence=rel_evidence,
        gap=parsed.gap,
        message=f"appended {parsed.amount_usd or 'NO AMOUNT'} to {book}",
        row=written,
        rows=[written],
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
