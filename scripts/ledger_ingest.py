#!/usr/bin/env python3
"""Drop a named receipt PDF or photo onto the SOVERYN or CWG tax book.

    python -m scripts.ledger_ingest --path /tmp/receipt.pdf
    python -m scripts.ledger_ingest --path /tmp/receipt.jpg --dry-run

A path is required. Folder-wide walks of data/intake/ledgers/ are refused.
Photos OCR via tesseract; garbled totals are not invented.
Does not file a return. Does not mix the two entities.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        action="append",
        required=True,
        help="Receipt PDF or photo (repeatable). Folder-wide ingest is refused.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and parse; do not copy evidence or append CSV.",
    )
    args = parser.parse_args(argv)

    from soveryn.platform.ledgers.classify import classify_receipt
    from soveryn.platform.ledgers.extract import RECEIPT_SUFFIXES, extract_receipt_path
    from soveryn.platform.ledgers.ingest import ingest_path
    from soveryn.platform.ledgers.parse import parse_receipt

    paths = [Path(p).expanduser() for p in args.path]
    for path in paths:
        if not path.is_file():
            print(f"ledger_ingest: not a file: {path}", file=sys.stderr)
            return 2
        if path.suffix.lower() not in RECEIPT_SUFFIXES:
            print(f"ledger_ingest: not a receipt suffix: {path}", file=sys.stderr)
            return 2

    if args.dry_run:
        for path in paths:
            extracted = extract_receipt_path(path)
            hit = classify_receipt(path.name, extracted.text or "")
            parsed = parse_receipt(extracted.text or "", source_name=path.name)
            print(
                f"{path.name}: book={hit.book} amount={parsed.amount_usd or 'NONE'} "
                f"order={parsed.order_id or '-'} status={parsed.status}"
                + (f" gap={hit.gap or parsed.gap}" if (hit.gap or parsed.gap) else "")
            )
        return 0

    results = [ingest_path(path, confirm=True) for path in paths]
    for r in results:
        extra = f" {r.amount_usd}" if r.amount_usd else ""
        gap = f" gap={r.gap}" if r.gap else ""
        print(f"{r.source_name}: {r.action} → {r.book}{extra}{gap}")
    print(json.dumps({"count": len(results), "actions": [r.action for r in results]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
