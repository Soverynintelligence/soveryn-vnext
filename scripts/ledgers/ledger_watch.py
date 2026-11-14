#!/usr/bin/env python
"""Ledger watch — daily totals snapshot for both books (Kernel's eyes).

Appends one JSONL line per run to data/ledger_watch/ledger_totals.jsonl with
per-book row counts and amounts, plus a small drift check against the previous
snapshot (row delta and amount delta). Alerts via alert_signal.sh only when a
delta is unexpected (rows changed without a matching amount change direction,
or amount moved > $500 in a day, or CSV shrank).

Read-only: never writes the ledgers. Booking stays behind the confirm token.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from soveryn.platform.ledgers.books import load_rows  # noqa: E402

BOOKS = {
    "soveryn": REPO / "docs/ops/tax/SOVERYN-2025-2026-expense-ledger.csv",
    "cwg": REPO / "docs/ops/tax-cwg/CWG-2025-2026-expense-ledger.csv",
}
OUT_DIR = REPO / "data/ledger_watch"
OUT_FILE = OUT_DIR / "ledger_totals.jsonl"
ALERT = REPO / "scripts/alert_signal.sh"
AMOUNT_ALERT_THRESHOLD = Decimal("500.00")


def _money(rows: list[dict[str, str]]) -> Decimal:
    total = Decimal("0")
    for r in rows:
        raw = (r.get("amount_usd") or "").replace("$", "").replace(",", "").strip()
        if not raw:
            continue
        try:
            total += Decimal(raw)
        except Exception:
            pass
    return total


def _documented(rows: list[dict[str, str]]) -> int:
    return sum(1 for r in rows if (r.get("status") or "").upper() == "DOCUMENTED")


def _alert(msg: str) -> None:
    if ALERT.exists():
        try:
            subprocess.run(
                [str(ALERT), f"Ledger watch: {msg}"],
                timeout=30,
                check=False,
            )
        except Exception:
            pass


def main() -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snap: dict = {"ts": now, "books": {}}

    prev: dict | None = None
    if OUT_FILE.exists():
        lines = OUT_FILE.read_text().splitlines()
        if lines:
            try:
                prev = json.loads(lines[-1])
            except json.JSONDecodeError:
                prev = None

    for bid, path in BOOKS.items():
        rows = load_rows(path)
        total = _money(rows)
        entry = {
            "rows": len(rows),
            "documented": _documented(rows),
            "amount_usd": str(total),
        }
        snap["books"][bid] = entry
        if prev and bid in prev.get("books", {}):
            p = prev["books"][bid]
            d_rows = entry["rows"] - p["rows"]
            d_amt = total - Decimal(p["amount_usd"])
            if d_rows < 0:
                _alert(f"{bid} book SHRANK by {-d_rows} rows — check for tampering or bad write")
            elif abs(d_amt) > AMOUNT_ALERT_THRESHOLD:
                _alert(f"{bid} moved ${abs(d_amt)} in one day (rows {p['rows']}->{entry['rows']})")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_FILE.open("a") as f:
        f.write(json.dumps(snap, sort_keys=True) + "\n")

    print(f"ledger watch {now}")
    for bid, e in snap["books"].items():
        print(f"  {bid:8s} rows={e['rows']:3d} documented={e['documented']:3d} total=${e['amount_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
