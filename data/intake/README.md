# Intake

Drop **md / txt / PDF** here (PDF must have a text layer — scans need OCR later).

Then:

```bash
cd ~/soveryn_vnext
python -m scripts.kb_ingest
```

Originals stay in this folder. Chunks + embeddings go to `data/kb/` (not the lattice). Eve and Aetheria pick them up on the next recall turn after vNext restart.

## Tax receipts (not the KB)

Drop Amazon/eBay/Cloudflare **PDFs or receipt photos** in `ledgers/` — they go to the tax CSVs, **not** the reference KB. Photos OCR like Expensify; garbled totals are not invented.

```
data/intake/ledgers/soveryn/   # SOVERYN Intelligence LLC
data/intake/ledgers/cwg/       # Carolina Water Gardens
data/intake/ledgers/unsorted/  # classifier decides, or holds gaps
```

```bash
python -m scripts.ledger_ingest --path /tmp/receipt.pdf
python -m scripts.ledger_ingest --path /tmp/receipt.jpg --dry-run
```

Name specific files. Folder-wide walks are refused. The agent tool previews first, then writes only with `confirm=true` and the returned token.

Books land in `docs/ops/tax/` and `docs/ops/tax-cwg/`. Pondwright customer quotes stay in `pondwright/` — do not drop those on a tax book.

No video. No passwords.
