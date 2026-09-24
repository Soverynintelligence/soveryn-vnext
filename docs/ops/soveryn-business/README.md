# SOVERYN business shelf (non-tax)

Compliance docs for SOVERYN Intelligence LLC. **Not** the tax book.

Paid receipts stay in [tax](../tax/README.md) via `file_away` dest `soveryn_evidence` then `ledger_ingest` book=soveryn.

| Folder | What goes here | `file_away` dest |
|---|---|---|
| `licenses/` | NC LLC articles, IRS EIN letter | `soveryn_licenses` |
| `insurance/` | COI / policies (not paid bills) | `soveryn_insurance` |
| `contracts/` | Vendor / customer contracts | `soveryn_contracts` |

EIN on the books (from the tax README, confirm against the letter when it lands): 42-1865323, assigned 2026-04-13.
