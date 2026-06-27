# Shepherd Drafting — Quarterly Issues/Programs List (Design, phase-2 slice 1)

**Date:** 2026-06-26
**Status:** Approved design (brainstormed + green-lit; revised after review).
**Builds on:** [[project_soveryn_shepherd_fcc_build]] — the engine, the lifecycle (missed/upcoming/done), the grounded chat agent on the swappable seam (Gemma), the "mark filed" overlay. Repo `~/shepherd`.
**Concept:** From a Quarterly Issues/Programs obligation on the calendar, the owner enters the quarter's community issues + the programs that addressed each (structured); the LLM (Gemma, via the swappable seam) formats those facts into a **DRAFT** Issues/Programs document — stamped "DRAFT — prepared by Shepherd; requires licensee & attorney review before filing," cited to §73.3526. The owner and their attorney review/edit it, file it themselves, and mark the obligation filed via the existing flow. **Shepherd drafts; a human + an attorney are in the loop; the licensee files.**

## Decisions (from brainstorming)

- **First filing: the Quarterly Issues/Programs list (§73.3526)** — highest frequency (4×/yr), a document the station authors, the clearest to format. Renewal/EEO drafting come later, same pattern.
- **Input: structured entry** — the owner lists each issue + the program(s) that addressed it (title, air date, duration, description); the LLM formats those facts. The substantive facts stay owner-supplied.
- **Posture: draft only.** No auto-submit. Human + attorney review; licensee files. (Jon: "the draft is the right call — needs a human and really a lawyer in the mix.")

## The honesty line for drafting — prompt-enforced posture, NOT a technical guarantee (the heart of this slice)

Until now the LLM only *read* the deterministic truth (the chat agent). Drafting is the first place it *authors* output. **Be precise about what that means, because this language will shape how the broadcast attorney evaluates the system:**

- The instruction "format ONLY the owner-provided facts; never invent an issue, program, date, duration, or any substantive content" is a **prompt-enforced bias, not a technical constraint.** An open-weight model (Gemma or any) *can* still hallucinate — invent transitional language implying facts not given, pad thin entries with plausible descriptions, or reformat a date/duration in a way that subtly changes meaning. We do NOT call this a "guarantee" or a "firewall."
- **The actual safeguards are layered, in order of strength:** (1) the deterministic engine supplies the deadline + the §73.3526 citation — the LLM never authors *those*; (2) the model receives ONLY the owner's entries + the requirements framing as its source; (3) the grounded system prompt biases it to format-not-invent; (4) **the human + attorney review is the real backstop** — the draft is explicitly for their review before filing, and nothing is auto-filed.
- **Document preparation, not legal advice.** The LLM fills a form from the owner's facts (a paralegal act); it does not advise what to decide.

So: the prompt reduces invention; the human/attorney catch what slips through; the deterministic layer owns the dates/citations. That honest stack — not a claimed guarantee — is the safety story.

## Architecture & components (each small, isolated, testable)

1. **Issue/program entry + draft store.** A draft record keyed to a specific obligation instance `(call_sign, rule_id, due_date)`: the structured `entries` (each `{issue, program_title, air_date, duration, description}`), the `draft_text`, a `status`, and a `filed_at` timestamp. **Status lifecycle: `draft` (entries being entered) → `generated` (LLM produced text) → `edited` (a human modified the text) → `filed` (the obligation was marked filed).** `filed_at` is set (and status → `filed`) when `/address` is called for that obligation, **linking the draft to the filing so the audit trail is complete** ("show me the filed draft for this obligation" is answerable). Persisted (SQLite, alongside `ProfileStore` or a sibling); resumable.
2. **Draft generator** (`shepherd/agent/draft.py`). `generate_draft(profile, obligation, entries, client) -> str` via the swappable seam (injected `ChatClient` — Gemma now). The model receives: the obligation (title + due date + §73.3526, from the engine), a short §73.3526 formatting-requirements block, and **only** the owner's `entries`. System prompt = the drafting honesty posture above. Fake-client tested (assert the prompt carries the format-not-invent rules + only the owner's entries + the citation; no live model in tests).
3. **Routes + UI.** From an Issues/Programs obligation on the calendar, a **"Draft this filing"** action → an entry form (add issues + programs) → **Generate** → the DRAFT shown for review/edit/regenerate → copy/download → the owner files (with attorney) and marks the obligation filed via the existing `/address`. Additive — never blocks the calendar.

### Regeneration semantics (defined — not left ambiguous)
**Regenerate is a hard overwrite of `draft_text`** (the structured `entries` are preserved and reused). If the draft is in `edited` status, the UI **warns before regenerating** ("Regenerating replaces the current draft text — your edits will be lost. Continue?"). No merge, no diff in v1 (versioning/diff is a later slice if needed). One behavior, documented, with a guard against silent data loss.

## Data flow

calendar (an I/P obligation) → "Draft this filing" → entry form → save entries (status `draft`) → `generate_draft` (LLM, grounded, facts-only; status `generated`) → DRAFT shown, stamped + cited → owner reviews/edits (status `edited`) → copy/download → files externally (attorney-reviewed) → marks the obligation filed (`/address` → draft `filed`, `filed_at` set). The draft record persists for the audit trail.

## Entry-form UX debt (named, not hidden)

The structured entry form is **the highest-friction point in the whole flow.** A quarter can have 5–15 issues with multiple programs each — 25–45+ manual entries. This is the part that kills adoption at 11pm on a Thursday. v1 ships the manual form (to prove the drafting pattern), but this is **known UX debt**, and **slice 2 prioritizes:** (a) **clone-from-last-quarter** (issues/programs recur heavily quarter to quarter — the highest-value reducer), and (b) **paste/spreadsheet import** (the owner pastes a log). Not building these in v1 is a deliberate scope cut, recorded here so it isn't mistaken for "done."

## Error handling

- **Additive:** LLM unavailable/errors → entries are saved, "can't generate right now — your entries are saved"; the deterministic calendar/tracking is untouched; never 500 the page. (Same fail-safe posture as the chat route.)
- **Empty entries** → don't generate; prompt the owner to add issues/programs.
- **Thin entries** → the draft reflects only what's given; the model is prompted not to pad (and the human catches padding that slips through).
- **Never auto-files**; the draft is always marked not-filed until the licensee acts.

## Testing

- **Draft store:** persist/retrieve by `(call_sign, rule_id, due_date)`; entries + draft_text + status + filed_at round-trip; the status transitions (draft→generated→edited→filed); `/address` sets `filed_at` + status `filed` on the linked draft; upsert.
- **Draft generator:** prompt assembly tested with a **fake client** — the system prompt contains the format-not-invent/draft/cite rules; the message includes the §73.3526 framing + ONLY the owner's entries (not other stations' data); the obligation's citation is present. No correctness test depends on a live model.
- **Stamp + citation** present in the assembled output path (the accurate "requires licensee & attorney review before filing" wording).
- **Regeneration:** overwrites draft_text, preserves entries; (UI-level warning verified by a render/smoke check).
- **Additive degradation:** generator error → entries saved, graceful message, calendar unaffected.

## Scope / out of scope

- **In:** the Quarterly Issues/Programs list (one filing type); structured issue/program entry; the draft store (with the full status lifecycle + filed_at audit link); the grounded draft generator; review/edit/regenerate/download; tie-in to "mark filed."
- **Out (later / YAGNI):** other filings (renewal, EEO — same pattern); **slice-2 entry helpers (clone-from-last-quarter, paste/import)** — named UX debt above; draft versioning/diff; a built attorney-sign-off workflow (the stamp *requires* review of the human; the system does not *enforce* a sign-off step in v1 — accurately worded, not claimed); auto-submission to the FCC (explicitly never — the licensee files); chat-driven drafting.

## Where it lives

`~/shepherd`: a draft store (on `ProfileStore` or a sibling `draft_store.py`); `shepherd/agent/draft.py` (the generator, reusing the swappable `ChatClient` + the drafting honesty system prompt); routes + UI (entry form + draft view) tied to the calendar's I/P obligations + the `/address` filed-link. Reuses the seam, the engine's obligation identity, and the existing fail-safe/honesty patterns.

## Dependencies / gates

- Reuses the swappable seam (Gemma now / sovereign on the Spark later — real client data only on-prem).
- **HARD GATE — no drafting in production until the broadcast attorney signs off the §73.3526 requirements block + the draft output framing.** The generator is built against a *provisional* §73.3526 requirements block; until the attorney signs off, the first drafts may be structurally wrong. The requirements block is *data/config*, so an attorney correction is a config change, not a code change — but production drafting is gated on that sign-off. (Extends the MVP's attorney gate to cover generated output + the disclaimers + the prep/advice line.)
