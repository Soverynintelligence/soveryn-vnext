"""CSV books. One file per entity. Append-only besides header create."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping

CSV_FIELDS: tuple[str, ...] = (
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


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows: list[dict[str, str]] = []
        for raw in reader:
            rows.append({k: (raw.get(k) or "").strip() for k in CSV_FIELDS})
        return rows


def _writer(fh) -> csv.DictWriter:
    return csv.DictWriter(
        fh,
        fieldnames=list(CSV_FIELDS),
        extrasaction="ignore",
        lineterminator="\n",
    )


def append_row(path: Path, row: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = _writer(fh)
        if new_file:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def write_rows(path: Path, rows: list[Mapping[str, str]]) -> None:
    """Rewrite a book in place. Used to drop a full-amount row before a split."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = _writer(fh)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def order_blob(row: Mapping[str, str]) -> str:
    return " ".join(row.get(k, "") for k in ("description", "notes", "evidence", "vendor"))


def rows_for_order(rows: list[dict[str, str]], order_id: str) -> list[dict[str, str]]:
    if not order_id:
        return []
    needle = order_id.strip().lower()
    return [row for row in rows if needle in order_blob(row).lower()]


def without_order(rows: list[dict[str, str]], order_id: str) -> list[dict[str, str]]:
    if not order_id:
        return list(rows)
    needle = order_id.strip().lower()
    return [row for row in rows if needle not in order_blob(row).lower()]


def has_order_id(rows: list[dict[str, str]], order_id: str) -> bool:
    return bool(rows_for_order(rows, order_id))
