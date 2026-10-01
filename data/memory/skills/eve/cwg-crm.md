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
- `pondwright_save_lead` — create one person, note, status (rules below)
- `pondwright_save_quote` — attach total + lines (creates the lead if needed)
- `pondwright_jobs` — list / start
- `pondwright_customers` — history by phone/email

If you cannot log into the website, **call the tools**. Do not ask Jon for a screenshot of Leads. Do not offer a parallel tracker.

## Saving a person (`pondwright_save_lead`) — rules from 2026-10-01
The CRM now rejects a new lead without **name + phone or email + job type + source**, and merges a repeat phone/email into the lead that already exists.
- **One person per save.** Two people in one message = two saves.
- **Never save from a photo alone.** A screenshot or picture is not a lead until Jon confirms who it is and gives a phone or email.
- **Missing phone and email?** Don't save. Ask Jon: "What's <name>'s phone or email?"
- **job_type**: Swim pond, New pond build, Waterfall/stream, Remodel/rebuild, Repair, Cleanout, Green water, Maintenance plan, Other. Leave it out and the tool guesses from what they want; if it can't tell, it won't save. Ask Jon what the job is.
- **source** (how they found CWG): Website/Google search, Google profile, Facebook, Instagram, Nextdoor, Yelp, Referral, Repeat customer, Other. If Jon doesn't say, leave it; the tool uses `Phone/text unknown`.
- **"CRM rejected: ..."** — tell Jon exactly that, in plain words (e.g. "CRM rejected: Need phone or email for Ervin"), and ask him for what's missing.
- **"Already in CRM as <name> (id …)"** — tell Jon that; your note went onto the existing lead. No new lead was made.
- **Never retry with blank or made-up fields.** No fake phone numbers, no "unknown" emails, no guessing the job to get past a rejection. Ask Jon.

## Documents vs index
- Quote paper (Pat template): `carolinawatergardens/quotes/` — HTML/PDF only.
- Molly: `quotes/2026-09-09-molly-thomas/` — **won**, $705, job scheduled. CRM lead `2528ada8407b49c982519c4a2ae3b0cd`.
- NEVER create `customers.json`. NEVER say “there’s no CRM.”

## When Jon talks quotes
1. `pondwright_leads` with the name.
2. If missing, `pondwright_save_lead` / `pondwright_save_quote`.
3. File the Pat-style HTML only as the customer PDF, then point the CRM at it.
