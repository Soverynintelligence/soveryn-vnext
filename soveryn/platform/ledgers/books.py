"""CSV books. One file per entity. All writes go through write_book."""

from __future__ import annotations

import csv
import fcntl
import io
import json
import os
import re
import shutil
import stat
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Mapping, Sequence

# Legacy columns stay first. New identity / amount columns are appended only.
LEGACY_FIELDS: tuple[str, ...] = (
    "tax_year",
    "date",
    "vendor",
    "description",
    "schedule_c_or_form",
    "amount_usd",
    "status",
    "payment_method",
    "evidence",
    "notes",
)

NEW_FIELDS: tuple[str, ...] = (
    "row_id",
    "evidence_sha256",
    "order_id",
    "subtotal",
    "shipping",
    "tax",
    "discount",
    "printed_total",
)

CSV_FIELDS: tuple[str, ...] = LEGACY_FIELDS + NEW_FIELDS

# Book status that drops a row from counted totals and duplicate grouping.
# check_book already skipped EXCLUDE from OPEN_AGING; one predicate everywhere.
EXCLUDE_STATUS = "EXCLUDE"

DEFAULT_BACKUP_KEEP = 8
BACKUP_KEEP_ENV = "LEDGER_BACKUP_KEEP"

# Never sniff. A quote-free sample makes csv.Sniffer pick doublequote=False
# (and no escapechar), which garbles later `12""` fields and then raises
# `_csv.Error: need to escape, but no escapechar set` on rewrite.
BOOK_CSV = csv.excel

_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()

# Whole-token match: "1216" must not hit "111-1216..." or "$1216.00".
_ORDER_BOUNDARY = r"(?<![\w.$-]){oid}(?![\w-]|\.\d)"


def new_row_id() -> str:
    return uuid.uuid4().hex


def backup_keep_default() -> int:
    raw = os.environ.get(BACKUP_KEEP_ENV, "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return DEFAULT_BACKUP_KEEP


def row_is_excluded(row: Mapping[str, str]) -> bool:
    """True when ``status`` is the exact book value ``EXCLUDE``.

    The amount stays on the row; callers decide whether to count it.
    """
    return (row.get("status") or "").strip() == EXCLUDE_STATUS


def parse_amount_usd(raw: str) -> Decimal | None:
    cleaned = (raw or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _quantize_usd(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def sum_amount_usd(
    rows: Sequence[Mapping[str, str]],
    *,
    skip_excluded: bool = False,
) -> str:
    """Sum ``amount_usd``. EXCLUDE amounts stay in place unless skipped."""
    total = Decimal("0.00")
    for row in rows:
        if skip_excluded and row_is_excluded(row):
            continue
        amount = parse_amount_usd(row.get("amount_usd") or "")
        if amount is not None:
            total += amount
    return _quantize_usd(total)


def counted_total_usd(rows: Sequence[Mapping[str, str]]) -> str:
    """Book total that skips EXCLUDE rows (the counted / printed Total)."""
    return sum_amount_usd(rows, skip_excluded=True)


def excluded_total_usd(rows: Sequence[Mapping[str, str]]) -> str:
    total = Decimal("0.00")
    for row in rows:
        if not row_is_excluded(row):
            continue
        amount = parse_amount_usd(row.get("amount_usd") or "")
        if amount is not None:
            total += amount
    return _quantize_usd(total)


def excluded_row_count(rows: Sequence[Mapping[str, str]]) -> int:
    return sum(1 for row in rows if row_is_excluded(row))


def changes_path(path: Path) -> Path:
    """`<book>.changes.jsonl` beside the book (book name includes .csv)."""
    return path.with_name(path.name + ".changes.jsonl")


def lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def _thread_lock(path: Path) -> threading.RLock:
    key = str(path.resolve()) if path.exists() else str(path)
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _THREAD_LOCKS[key] = lock
        return lock


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(now: datetime | None = None) -> str:
    return (now or _utc_now()).strftime("%Y%m%d-%H%M%S-%f")


def _iso(now: datetime | None = None) -> str:
    return (now or _utc_now()).isoformat(timespec="seconds")


@dataclass(frozen=True)
class ChangeRecord:
    action: str
    row_id: str
    before: Mapping[str, str] | None
    after: Mapping[str, str] | None
    reason: str = ""

    def as_json_line(self, *, actor: str, timestamp: str) -> str:
        payload = {
            "timestamp": timestamp,
            "actor": actor,
            "action": self.action,
            "row_id": self.row_id,
            "before": dict(self.before) if self.before is not None else None,
            "after": dict(self.after) if self.after is not None else None,
            "reason": self.reason,
        }
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _split_keepends(data: bytes) -> list[bytes]:
    """Split on CR/LF/CRLF while keeping each line's original ending."""
    lines: list[bytes] = []
    start = 0
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        if b == 0x0D:
            if i + 1 < n and data[i + 1] == 0x0A:
                lines.append(data[start : i + 2])
                i += 2
            else:
                lines.append(data[start : i + 1])
                i += 1
            start = i
        elif b == 0x0A:
            lines.append(data[start : i + 1])
            i += 1
            start = i
        else:
            i += 1
    if start < n:
        lines.append(data[start:])
    return lines


def _ending_of(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return b"\r\n"
    if line.endswith(b"\n"):
        return b"\n"
    if line.endswith(b"\r"):
        return b"\r"
    return b"\n"


def _strip_ending(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return line[:-2]
    if line.endswith((b"\n", b"\r")):
        return line[:-1]
    return line


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8")


def _csv_cells(line: str) -> list[str]:
    """Parse one physical line as standard comma CSV (csv.excel)."""
    return next(csv.reader([line], dialect=BOOK_CSV), [])


@dataclass
class LoadedBook:
    path: Path
    header: list[str]
    header_raw: bytes | None
    rows: list[dict[str, str]]
    row_raw: list[bytes | None]
    dialect: csv.Dialect
    default_ending: bytes
    exists: bool


def _blank_row(header: Sequence[str]) -> dict[str, str]:
    row = {k: "" for k in header}
    for k in CSV_FIELDS:
        row.setdefault(k, "")
    return row


def _parse_row(values: Mapping[str, str | None], header: Sequence[str]) -> dict[str, str]:
    row = {k: (values.get(k) or "").strip() for k in header}
    for k in CSV_FIELDS:
        row.setdefault(k, "")
    return row


def load_book(path: Path) -> LoadedBook:
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return LoadedBook(
            path=path,
            header=list(CSV_FIELDS),
            header_raw=None,
            rows=[],
            row_raw=[],
            dialect=BOOK_CSV,
            default_ending=b"\n",
            exists=False,
        )
    data = path.read_bytes()
    raw_lines = _split_keepends(data)
    if not raw_lines:
        return LoadedBook(
            path=path,
            header=list(CSV_FIELDS),
            header_raw=None,
            rows=[],
            row_raw=[],
            dialect=BOOK_CSV,
            default_ending=b"\n",
            exists=True,
        )
    header_line = _decode(_strip_ending(raw_lines[0]))
    header = [cell.strip() for cell in _csv_cells(header_line)]
    if not header:
        header = list(LEGACY_FIELDS)
    rows: list[dict[str, str]] = []
    row_raw: list[bytes | None] = []
    data_lines = [line for line in raw_lines[1:] if _strip_ending(line).strip()]
    for raw in data_lines:
        cells = _csv_cells(_decode(_strip_ending(raw)))
        values = {name: (cells[i] if i < len(cells) else "") for i, name in enumerate(header)}
        rows.append(_parse_row(values, header))
        row_raw.append(raw)
    ending = _ending_of(raw_lines[0])
    return LoadedBook(
        path=path,
        header=header,
        header_raw=raw_lines[0],
        rows=rows,
        row_raw=row_raw,
        dialect=BOOK_CSV,
        default_ending=ending,
        exists=True,
    )


def load_rows(path: Path) -> list[dict[str, str]]:
    """Read a book. Missing new columns become empty strings."""
    return [dict(row) for row in load_book(path).rows]


def _output_header(existing: Sequence[str], *, ensure_new_columns: bool) -> list[str]:
    header = list(existing) if existing else list(CSV_FIELDS)
    if not header:
        header = list(CSV_FIELDS)
    if ensure_new_columns:
        known = set(header)
        for name in NEW_FIELDS:
            if name not in known:
                header.append(name)
                known.add(name)
    return header


def _serialize_line(
    row: Mapping[str, str],
    header: Sequence[str],
    ending: bytes,
) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(
        buf,
        fieldnames=list(header),
        extrasaction="ignore",
        lineterminator="",
        dialect=BOOK_CSV,
        quoting=csv.QUOTE_MINIMAL,
        doublequote=True,
        quotechar='"',
    )
    writer.writerow({k: row.get(k, "") for k in header})
    return buf.getvalue().encode("utf-8") + ending


def _serialize_header(header: Sequence[str], ending: bytes) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(
        buf,
        fieldnames=list(header),
        extrasaction="ignore",
        lineterminator="",
        dialect=BOOK_CSV,
        quoting=csv.QUOTE_MINIMAL,
        doublequote=True,
        quotechar='"',
    )
    writer.writeheader()
    return buf.getvalue().encode("utf-8") + ending


def _row_bytes_reusable(
    original: Mapping[str, str],
    current: Mapping[str, str],
    orig_header: Sequence[str],
) -> bool:
    for key in orig_header:
        if (original.get(key) or "") != (current.get(key) or ""):
            return False
    extra = set(CSV_FIELDS) - set(orig_header)
    for key in extra:
        if current.get(key):
            return False
    return True


def render_book_bytes(
    loaded: LoadedBook,
    rows: Sequence[Mapping[str, str]],
    *,
    ensure_new_columns: bool = True,
) -> bytes:
    """Render the book. Unchanged existing lines keep their original bytes."""
    header = _output_header(loaded.header, ensure_new_columns=ensure_new_columns)
    ending = loaded.default_ending or b"\n"
    parts: list[bytes] = []
    if (
        loaded.header_raw is not None
        and list(loaded.header) == header
    ):
        parts.append(loaded.header_raw)
    else:
        parts.append(_serialize_header(header, ending))

    orig_by_id: dict[str, tuple[dict[str, str], bytes | None]] = {}
    orig_queue: list[tuple[dict[str, str], bytes | None]] = []
    for old, raw in zip(loaded.rows, loaded.row_raw, strict=False):
        rid = (old.get("row_id") or "").strip()
        if rid and rid not in orig_by_id:
            orig_by_id[rid] = (old, raw)
        orig_queue.append((old, raw))

    used_raw: set[int] = set()
    for row in rows:
        rid = (row.get("row_id") or "").strip()
        matched: tuple[dict[str, str], bytes | None] | None = None
        if rid and rid in orig_by_id:
            matched = orig_by_id[rid]
        else:
            for i, (old, raw) in enumerate(orig_queue):
                if i in used_raw or raw is None:
                    continue
                if _row_bytes_reusable(old, row, loaded.header):
                    matched = (old, raw)
                    used_raw.add(i)
                    break
        if matched is not None and matched[1] is not None and _row_bytes_reusable(
            matched[0], row, loaded.header
        ):
            parts.append(matched[1])
        else:
            parts.append(_serialize_line(row, header, ending))
    return b"".join(parts)


def _fsync_dir(directory: Path) -> None:
    fd = os.open(str(directory), os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_replace(path: Path, data: bytes) -> None:
    """Write ``data`` then replace ``path``. Preserve an existing file's mode.

    The temp file is created with ``os.open(..., 0o666)`` so the kernel
    applies the current umask (thread-safe; no process-wide ``os.umask``
    dance). If the target exists, copy its permission bits onto the temp
    file before ``os.replace``. Ownership is left alone.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode: int | None = None
    if path.exists():
        existing_mode = stat.S_IMODE(os.stat(path).st_mode)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if existing_mode is not None:
            os.chmod(str(tmp), existing_mode)
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _backup_path(path: Path, stamp: str) -> Path:
    return path.with_name(f"{path.name}.bak-{stamp}")


def _prune_backups(path: Path, keep: int) -> None:
    prefix = f"{path.name}.bak-"
    backups = sorted(
        p for p in path.parent.iterdir() if p.name.startswith(prefix) and p.is_file()
    )
    extra = len(backups) - keep
    if extra <= 0:
        return
    for old in backups[:extra]:
        try:
            old.unlink()
        except OSError:
            pass


def _append_changelog(
    path: Path,
    changes: Sequence[ChangeRecord],
    *,
    actor: str,
    timestamp: str,
) -> None:
    if not changes:
        return
    log = changes_path(path)
    lines = "".join(
        rec.as_json_line(actor=actor, timestamp=timestamp) + "\n" for rec in changes
    )
    with log.open("a", encoding="utf-8") as fh:
        fh.write(lines)
        fh.flush()
        os.fsync(fh.fileno())


@contextmanager
def exclusive_book(path: Path) -> Iterator[None]:
    """Exclusive process + thread lock for one book.

    flock is always released in ``finally`` so a failed write cannot leave
    a lock that blocks the next writer. The ``.lock`` file is only an
    inode for flock; leftover empty files do not hold the lock.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    thread = _thread_lock(path)
    lock_file = lock_path(path)
    thread.acquire()
    fh = None
    try:
        fh = lock_file.open("a+")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if fh is not None:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                fh.close()
            except OSError:
                pass
        thread.release()


def _write_book_unlocked(
    path: Path,
    rows: Sequence[Mapping[str, str]],
    *,
    actor: str,
    changes: Sequence[ChangeRecord],
    reason: str = "",
    backup_keep: int | None = None,
    ensure_new_columns: bool = True,
) -> list[dict[str, str]]:
    path = Path(path)
    keep = backup_keep if backup_keep is not None else backup_keep_default()
    now = _utc_now()
    stamp = _stamp(now)
    timestamp = _iso(now)
    prepared: list[dict[str, str]] = []
    for raw in rows:
        row = {k: (raw.get(k) or "") for k in CSV_FIELDS}
        for key, value in raw.items():
            if key not in row:
                row[key] = value or ""
        prepared.append(row)

    logged = list(changes)
    if not logged:
        logged = [
            ChangeRecord(
                action="rewrite",
                row_id="",
                before=None,
                after={"rows": str(len(prepared))},
                reason=reason,
            )
        ]

    loaded = load_book(path)
    backup: Path | None = None
    replaced = False
    try:
        if loaded.exists and path.is_file() and path.stat().st_size > 0:
            backup = _backup_path(path, stamp)
            shutil.copy2(path, backup)
            try:
                with backup.open("rb") as fh:
                    os.fsync(fh.fileno())
            except OSError:
                pass
            _prune_backups(path, keep)
        payload = render_book_bytes(
            loaded, prepared, ensure_new_columns=ensure_new_columns
        )
        _atomic_replace(path, payload)
        replaced = True
        _append_changelog(path, logged, actor=actor, timestamp=timestamp)
        return prepared
    except Exception:
        # Original file is intact if replace never ran; drop the spare backup
        # so a failed serialize does not leave a stray .bak-* beside the book.
        if not replaced and backup is not None:
            try:
                backup.unlink()
            except OSError:
                pass
        raise


def write_book(
    path: Path,
    rows: Sequence[Mapping[str, str]],
    *,
    actor: str,
    changes: Sequence[ChangeRecord],
    reason: str = "",
    backup_keep: int | None = None,
    ensure_new_columns: bool = True,
    already_locked: bool = False,
) -> list[dict[str, str]]:
    """Single writer: lock, backup, atomic replace, changelog.

    Unchanged lines keep their original bytes (quoting and endings) so
    mixed CRLF/LF books stay mixed. New or edited lines are written as
    standard comma CSV (csv.excel: doublequote, QUOTE_MINIMAL).
    """
    if already_locked:
        return _write_book_unlocked(
            path,
            rows,
            actor=actor,
            changes=changes,
            reason=reason,
            backup_keep=backup_keep,
            ensure_new_columns=ensure_new_columns,
        )
    with exclusive_book(path):
        return _write_book_unlocked(
            path,
            rows,
            actor=actor,
            changes=changes,
            reason=reason,
            backup_keep=backup_keep,
            ensure_new_columns=ensure_new_columns,
        )


def append_row(
    path: Path,
    row: Mapping[str, str],
    *,
    actor: str = "append_row",
    reason: str = "append",
    backup_keep: int | None = None,
) -> dict[str, str]:
    """Append one row through the single writer. Returns the stored row."""
    incoming = dict(row)
    if not incoming.get("row_id"):
        incoming["row_id"] = new_row_id()
    with exclusive_book(path):
        existing = load_rows(path)
        written = _write_book_unlocked(
            path,
            existing + [incoming],
            actor=actor,
            changes=[
                ChangeRecord(
                    action="append",
                    row_id=incoming["row_id"],
                    before=None,
                    after=incoming,
                    reason=reason,
                )
            ],
            reason=reason,
            backup_keep=backup_keep,
        )
    return written[-1] if written else incoming


def write_rows(
    path: Path,
    rows: list[Mapping[str, str]],
    *,
    actor: str = "write_rows",
    reason: str = "rewrite",
    changes: Sequence[ChangeRecord] | None = None,
    backup_keep: int | None = None,
) -> list[dict[str, str]]:
    """Rewrite a book through the single writer."""
    return write_book(
        path,
        rows,
        actor=actor,
        changes=list(changes or ()),
        reason=reason,
        backup_keep=backup_keep,
    )


def order_blob(row: Mapping[str, str]) -> str:
    return " ".join(
        row.get(k, "")
        for k in ("description", "notes", "evidence", "vendor", "order_id")
    )


def _order_rx(order_id: str) -> re.Pattern[str]:
    return re.compile(_ORDER_BOUNDARY.format(oid=re.escape(order_id.strip())), re.I)


def rows_for_order(rows: list[dict[str, str]], order_id: str) -> list[dict[str, str]]:
    if not order_id or not order_id.strip():
        return []
    needle = order_id.strip()
    hits: list[dict[str, str]] = []
    rx = _order_rx(needle)
    for row in rows:
        if (row.get("order_id") or "").strip() == needle:
            hits.append(row)
            continue
        if rx.search(order_blob(row)):
            hits.append(row)
    return hits


def without_order(rows: list[dict[str, str]], order_id: str) -> list[dict[str, str]]:
    if not order_id or not order_id.strip():
        return list(rows)
    drop = {id(row) for row in rows_for_order(rows, order_id)}
    return [row for row in rows if id(row) not in drop]


def has_order_id(rows: list[dict[str, str]], order_id: str) -> bool:
    return bool(rows_for_order(rows, order_id))


def row_by_id(rows: Sequence[Mapping[str, str]], row_id: str) -> dict[str, str] | None:
    rid = (row_id or "").strip()
    if not rid:
        return None
    for row in rows:
        if (row.get("row_id") or "").strip() == rid:
            return dict(row)
    return None


def find_duplicate(
    rows: Sequence[Mapping[str, str]],
    *,
    row_id: str = "",
    evidence_sha256: str = "",
    order_id: str = "",
) -> dict[str, str] | None:
    """First existing row matching row_id, evidence hash, or order id."""
    rid = (row_id or "").strip()
    digest = (evidence_sha256 or "").strip().lower()
    oid = (order_id or "").strip()
    if rid:
        hit = row_by_id(rows, rid)
        if hit is not None:
            return hit
    if digest:
        for row in rows:
            if (row.get("evidence_sha256") or "").strip().lower() == digest:
                return dict(row)
    if oid:
        hits = rows_for_order([dict(r) for r in rows], oid)
        if hits:
            return dict(hits[0])
    return None


def archive_removed_rows(
    book_path: Path,
    rows: Sequence[Mapping[str, str]],
    *,
    stamp: str | None = None,
) -> Path:
    """Write removed rows beside the book. Never silently delete."""
    when = stamp or _stamp()
    dest = book_path.parent / f"duplicates-removed-{when}.csv"
    header = list(CSV_FIELDS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=header,
            extrasaction="ignore",
            lineterminator="\n",
            dialect=BOOK_CSV,
            quoting=csv.QUOTE_MINIMAL,
            doublequote=True,
            quotechar='"',
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in header})
    return dest


def _field_changes(
    before: Mapping[str, str],
    after: Mapping[str, str] | None,
) -> list[dict[str, str]]:
    after_map = after or {}
    keys = list(dict.fromkeys([*CSV_FIELDS, *before.keys(), *after_map.keys()]))
    changes: list[dict[str, str]] = []
    for key in keys:
        left = "" if before.get(key) is None else str(before.get(key, ""))
        right = "" if after is None else str(after_map.get(key, "") or "")
        if left != right:
            changes.append({"field": key, "before": left, "after": right})
    return changes


def _total_change(
    before_rows: Sequence[Mapping[str, str]],
    after_rows: Sequence[Mapping[str, str]],
) -> dict[str, str]:
    before_usd = counted_total_usd(before_rows)
    after_usd = counted_total_usd(after_rows)
    delta = Decimal(after_usd) - Decimal(before_usd)
    return {
        "before_usd": before_usd,
        "after_usd": after_usd,
        "delta_usd": _quantize_usd(delta),
    }


def _planned_amend(
    existing: Sequence[Mapping[str, str]],
    current: Mapping[str, str],
    *,
    rid: str,
    updates: Mapping[str, str] | None,
    remove: bool,
) -> tuple[list[dict[str, str]], dict[str, str] | None]:
    if remove:
        kept = [row for row in existing if (row.get("row_id") or "").strip() != rid]
        return kept, None
    allowed = set(CSV_FIELDS)
    after = dict(current)
    for key, value in (updates or {}).items():
        if key not in allowed:
            raise ValueError(f"unknown ledger column: {key}")
        if key == "row_id":
            raise ValueError("row_id cannot be changed")
        after[key] = "" if value is None else str(value)
    after["row_id"] = rid
    next_rows = [
        after if (row.get("row_id") or "").strip() == rid else dict(row)
        for row in existing
    ]
    return next_rows, after


def amend_row(
    path: Path,
    row_id: str,
    *,
    reason: str,
    updates: Mapping[str, str] | None = None,
    remove: bool = False,
    actor: str = "ledger_amend",
    backup_keep: int | None = None,
    confirm: bool = False,
) -> dict[str, object]:
    """Preview (default) or confirm an edit/remove of one row by row_id.

    Without ``confirm=True`` this returns the row, field-by-field before/after,
    and the counted-total change, and writes nothing. Reason is required.
    """
    why = (reason or "").strip()
    if not why:
        raise ValueError("ledger_amend requires a reason")
    rid = (row_id or "").strip()
    if not rid:
        raise ValueError("ledger_amend requires row_id")
    if remove and updates:
        raise ValueError("ledger_amend cannot edit and remove in one call")
    if not remove and not updates:
        raise ValueError("ledger_amend needs updates or remove=true")

    with exclusive_book(path):
        existing = load_rows(path)
        current = row_by_id(existing, rid)
        if current is None:
            return {"ok": False, "action": "missing", "row_id": rid, "reason": why}
        next_rows, after = _planned_amend(
            existing, current, rid=rid, updates=updates, remove=remove
        )
        payload: dict[str, object] = {
            "ok": True,
            "action": "preview",
            "would": "remove" if remove else "edit",
            "row_id": rid,
            "reason": why,
            "row": current,
            "before": current,
            "after": after,
            "fields": _field_changes(current, after),
            "total_change": _total_change(existing, next_rows),
            "written": False,
        }
        if not confirm:
            return payload
        if remove:
            archive = archive_removed_rows(path, [current])
            _write_book_unlocked(
                path,
                next_rows,
                actor=actor,
                changes=[
                    ChangeRecord(
                        action="remove",
                        row_id=rid,
                        before=current,
                        after=None,
                        reason=why,
                    )
                ],
                reason=why,
                backup_keep=backup_keep,
            )
            payload["action"] = "removed"
            payload["written"] = True
            payload["archive"] = str(archive)
            return payload
        _write_book_unlocked(
            path,
            next_rows,
            actor=actor,
            changes=[
                ChangeRecord(
                    action="edit",
                    row_id=rid,
                    before=current,
                    after=after,
                    reason=why,
                )
            ],
            reason=why,
            backup_keep=backup_keep,
        )
        payload["action"] = "edited"
        payload["written"] = True
        return payload


# Re-export for callers that imported asdict from here in tests.
__all__ = [
    "CSV_FIELDS",
    "ChangeRecord",
    "EXCLUDE_STATUS",
    "LEGACY_FIELDS",
    "NEW_FIELDS",
    "amend_row",
    "append_row",
    "counted_total_usd",
    "changes_path",
    "excluded_row_count",
    "excluded_total_usd",
    "sum_amount_usd",
    "exclusive_book",
    "find_duplicate",
    "has_order_id",
    "load_book",
    "load_rows",
    "new_row_id",
    "order_blob",
    "parse_amount_usd",
    "row_by_id",
    "row_is_excluded",
    "rows_for_order",
    "without_order",
    "write_book",
    "write_rows",
]
