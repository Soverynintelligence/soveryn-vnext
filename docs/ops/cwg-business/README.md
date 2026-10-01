# CWG business shelf (non-tax)

Compliance and ops docs for Carolina Water Gardens. **Not** the tax book.

Paid receipts and insurance **bills** stay in [tax-cwg](../tax-cwg/README.md) via `file_away` dest `cwg_evidence` then `ledger_ingest` book=cwg. Customer quotes stay in CRM, not here.

| Folder | What goes here | `file_away` dest |
|---|---|---|
| `insurance/` | COI, policies, certificates | `cwg_insurance` |
| `licenses/` | NC LLC articles, IRS EIN letter | `cwg_licenses` |
| `vehicles/` | Title, registration | `cwg_vehicles` |
| `contracts/` | Vendor / supplier contracts | `cwg_contracts` |

Do **not** put paid insurance bills in `insurance/` — those are tax evidence.
