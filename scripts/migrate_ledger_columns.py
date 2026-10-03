#!/usr/bin/env python3
"""Add identity/amount columns to a ledger CSV and back-fill hashes.

Dry-run by default. Does not run automatically. Do not point this at a
live tax book unless you have a backup and pass --apply.

    python -m scripts.migrate_ledger_columns --path /tmp/book.csv
    python -m scripts.migrate_ledger_columns --path /tmp/book.csv --apply

Adds, at the END of the header only:

    row_id, evidence_sha256, order_id, subtotal, shipping, tax, discount, printed_total

Back-fills row_id for every row that lacks one, and evidence_sha256 when
the evidence file exists next to the book (``<book-dir>/<evidence>`` or
``<book-dir>/evidence/...``).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_file(book: Path, rel: str) -> Path | None:
    rel = (rel or "").strip()
    if not rel:
        return None
    candidates = [book.parent / rel]
    if rel.startswith("evidence/"):
        candidates.append(book.parent / "evidence" / rel[len("evidence/") :])
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def plan_migration(path: Path) -> dict:
    from soveryn.platform.ledgers.books import NEW_FIELDS, load_book, new_row_id

    loaded = load_book(path)
    missing_cols = [name for name in NEW_FIELDS if name not in loaded.header]
    planned = []
    fills = 0
    hashes = 0
    for row in loaded.rows:
        after = dict(row)
        changed = False
        if not (after.get("row_id") or "").strip():
            after["row_id"] = new_row_id()
            changed = True
            fills += 1
        if not (after.get("evidence_sha256") or "").strip():
            ev = _evidence_file(path, after.get("evidence", ""))
            if ev is not None:
                after["evidence_sha256"] = _sha256(ev)
                changed = True
                hashes += 1
        planned.append(after)
        if not changed:
            planned[-1] = row
    return {
        "path": str(path),
        "rows": len(loaded.rows),
        "missing_columns": missing_cols,
        "row_ids_to_fill": fills,
        "hashes_to_fill": hashes,
        "rows_out": planned,
    }


def apply_migration(path: Path, plan: dict, *, actor: str = "migrate_ledger_columns") -> None:
    from soveryn.platform.ledgers.books import ChangeRecord, write_book

    write_book(
        path,
        plan["rows_out"],
        actor=actor,
        changes=[
            ChangeRecord(
                action="migrate",
                row_id="",
                before={"missing_columns": ",".join(plan["missing_columns"])},
                after={
                    "row_ids_to_fill": str(plan["row_ids_to_fill"]),
                    "hashes_to_fill": str(plan["hashes_to_fill"]),
                },
                reason="add identity/amount columns; back-fill row_id and evidence_sha256",
            )
        ],
        reason="add identity/amount columns; back-fill row_id and evidence_sha256",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        required=True,
        help="One CSV book (synthetic / tmp). Dry-run unless --apply.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the migration. Default is dry-run (print the plan only).",
    )
    args = parser.parse_args(argv)
    path = Path(args.path).expanduser()
    if not path.is_file():
        print(f"migrate_ledger_columns: not a file: {path}", file=sys.stderr)
        return 2
    plan = plan_migration(path)
    print(
        f"{path}: rows={plan['rows']} missing_columns={plan['missing_columns'] or 'none'} "
        f"row_ids_to_fill={plan['row_ids_to_fill']} hashes_to_fill={plan['hashes_to_fill']}"
    )
    if not args.apply:
        print("dry-run (no write). Pass --apply to write.")
        return 0
    apply_migration(path, plan)
    print("applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
