# Receipts and the money books — one path, no drift

Jon 2026-09-18: "this needs to be right, it's for taxes." Receipts are the
house's tax spine. Never freelance a filing location.

## The only path

1. Jon sends a receipt (photo, PDF, screenshot) in chat.
2. `file_away` to the right bucket — never a hand-picked folder:
   - CWG paid receipt → dest `cwg_evidence`
   - SOVERYN paid receipt → dest `soveryn_evidence`
   (insurance certificates / licenses are NOT receipts → `cwg_insurance`,
   `soveryn_licenses` shelves)
3. `ledger_ingest` on a **named** file (path / image="current" / order_id+splits).
   First call is a preview: the exact rows that would be added, plus a
   short-lived `confirm_token`. It writes nothing. Call again with
   `confirm=true` and that token to write. Folder-wide re-ingest is refused.
   Re-submitting the same receipt is a safe no-op that returns the existing
   row. Totals that do not match within a cent are blocked unless
   `override_reason` is given. Math in notes: subtotal + shipping + tax −
   discount = printed total.
4. `ledger_amend` edits or removes a row by `row_id` (reason required; removed
   rows go to `duplicates-removed-*.csv`). First call is a preview: the row,
   field-by-field before/after, and the would-be counted total change. It
   writes nothing. Call again with `confirm=true` to write. `ledger_reconcile`
   is read-only audit (duplicates, missing evidence, orphans, counts/totals;
   total_usd is the raw sum, counted_usd skips EXCLUDE rows).
5. Done. If the ledger row can't be written (missing amount, can't read the
   image), file it anyway and say what's missing. Never park a receipt in
   Downloads, Desktop, or quotes/.

## Never

- NEVER file receipts into `carolinawatergardens/quotes/` — that shelf is
  customer quote/invoice paper only (money IN). Receipts are money OUT.
- NEVER leave evidence at `evidence/attachment-1.pdf` style names — the
  bucket gives `YYYY-MM-DD_vendor_description_amount.ext`.
- NEVER mark a row DOCUMENTED without a real evidence file path. "Downloads/…"
  or "need invoice" in the evidence column is drift; the weekly check flags it.
- NEVER delete a receipt or duplicate silently — duplicates go to
  `evidence/superseded/` and the ledger note says why.

## The weekly check

`soveryn-ledger-reconcile.timer` runs Monday 08:30
(`python -m soveryn.platform.ledgers.reconcile --notify`). It compares both
books against their evidence trees and webpushes Jon on drift. If it fires:
read `docs/ops/tax/RECONCILE-LATEST.md`, fix the named items in the same
session, and tell Jon what was fixed.

## Decoding receipts

Text-layer PDFs and photos both decode: `ledgers/extract.py`
(`extract_receipt_path`) does pdftotext, falls back to tesseract OCR for
scans/photos. If OCR comes back garbage (bad angle, glare), say so and ask
Jon for the numbers — never guess an amount into the ledger.
