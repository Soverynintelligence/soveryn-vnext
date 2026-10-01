# CWG CRM — do not invent a second book

Jon 2026-09-09: you told him there was no CRM and offered to build `customers.json` under `carolinawatergardens/quotes/`. That was wrong. The CRM already exists.

## The book
- Admin: https://crm.pondwright.com/  (Leads)
- Estimator: https://estimator.pondwright.com/
- Code: `~/pondwright-cwg-ops/` on the Spark — **not** the old `pondwright-crm/` sqlite, **not** inside `carolinawatergardens/`
- Auth: Eve ops Basic (`OPS_USERS`). The old field token does not open Leads.

It stores **leads, quotes, jobs, customers**. Status: new → contacted → quoted → won / lost.

## Your tools (use these)
- `pondwright_leads` — list/search/get (query name/phone/email)
- `pondwright_save_lead` — create, note, status
- `pondwright_save_quote` — attach total + lines (creates the lead if needed)
- `pondwright_jobs` — list / start
- `pondwright_customers` — history by phone/email

If you cannot log into the website, **call the tools**. Do not ask Jon for a screenshot of Leads. Do not offer a parallel tracker.

## Documents vs index
- Quote paper (Pat template): `carolinawatergardens/quotes/` — HTML/PDF only.
- Molly: `quotes/2026-09-09-molly-thomas/` — **won**, $705, job scheduled. CRM lead `2528ada8407b49c982519c4a2ae3b0cd`.
- NEVER create `customers.json`. NEVER say “there’s no CRM.”

## When Jon talks quotes
1. `pondwright_leads` with the name.
2. If missing, `pondwright_save_lead` / `pondwright_save_quote`.
3. File the Pat-style HTML only as the customer PDF, then point the CRM at it.
