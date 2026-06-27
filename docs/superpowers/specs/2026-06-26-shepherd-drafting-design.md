# Shepherd Drafting — Quarterly Issues/Programs List (Design, phase-2 slice 1)

**Date:** 2026-06-26
**Status:** Approved design (brainstormed + green-lit).
**Builds on:** [[project_soveryn_shepherd_fcc_build]] — the engine, the lifecycle (missed/upcoming/done), the grounded chat agent on the swappable seam (Gemma), the "mark filed" overlay. Repo `~/shepherd`.
**Concept:** From a Quarterly Issues/Programs obligation on the calendar, the owner enters the quarter's community issues + the programs that addressed each (structured); the LLM (Gemma, via the swappable seam) formats those facts into a compliant **DRAFT** Issues/Programs document — stamped "DRAFT — for licensee & attorney review, not filed," cited to §73.3526. The owner and their attorney review/edit it, file it themselves, and mark the obligation filed via the existing flow. **Shepherd drafts; a human + an attorney are in the loop; the licensee files.**

## Decisions (from brainstorming)

- **First filing: the Quarterly Issues/Programs list (§73.3526)** — highest frequency (4×/yr), a document the station authors, the clearest to format. Renewal/EEO drafting come later, same pattern.
- **Input: structured entry** — the owner lists each issue + the program(s) that addressed it (title, air date, duration, description); the LLM formats those facts. The substantive facts stay owner-supplied.
- **Posture: draft only.** No auto-submit. Human + attorney review; licensee files. (Confirmed by Jon: "the draft is the right call — needs a human and really a lawyer in the mix.")

## The honesty line for drafting (the heart of this slice)

Until now the LLM only *read* the deterministic truth (the chat agent). Drafting is the first place it *authors* output, so the firewall shifts:

- **The LLM may format ONLY the owner-provided facts. It must never invent an issue, a program, a date, a duration, or any substantive content.** The system prompt enforces this: format the given entries into the required structure, add nothing substantive, no embellishment, no filler issues/programs.
- **The deadline and the citation come from the deterministic engine, not the LLM** (the draft is generated *for* a specific computed obligation instance).
- **Every draft is stamped "DRAFT — for licensee & attorney review, NOT filed"** and cites §73.3526.
- **Document preparation, not legal advice.** The LLM fills a form from the owner's facts (a paralegal act); it does not advise what to decide. Human + attorney are the backstop; nothing auto-files.
- The no-invention guarantee is enforced by the grounded prompt + the human/attorney review — the same posture as the chat agent's grounding, applied to generated output.

## Architecture & components (each small, isolated, testable)

1. **Issue/program entry + draft store.** A draft record keyed to a specific obligation instance `(call_sign, rule_id, due_date)`: the structured `entries` (each `{issue, program_title, air_date, duration, description}`), the generated `draft_text`, and a `status` (`draft`/`generated`). Persisted (SQLite, alongside `ProfileStore` or a sibling) so a draft is resumable. The key ties a draft to the exact obligation it satisfies.
2. **Draft generator** (`shepherd/agent/draft.py`). `generate_draft(profile, obligation, entries, client) -> str` via the swappable seam (injected `ChatClient` — Gemma now). The model receives: the obligation (title + due date + §73.3526, from the engine), a short §73.3526 formatting-requirements block, and **only** the owner's `entries`. System prompt = the drafting honesty law above. Fake-client tested (assert the prompt carries the honesty rules + only the owner's entries + the citation; no live model in tests).
3. **Routes + UI.** From an Issues/Programs obligation on the calendar (missed or upcoming), a **"Draft this filing"** action → an entry form (add issues + programs) → **Generate** → the DRAFT shown for review/edit/regenerate → copy/download → the owner files (with attorney) and marks the obligation filed via the existing `/address`. Additive — never blocks the calendar.

## Data flow

calendar (an I/P obligation) → "Draft this filing" → entry form (issues + programs) → save entries (draft store) → `generate_draft` (LLM, grounded, facts-only) → DRAFT text shown, stamped + cited → owner reviews/edits → copy/download → files externally (attorney-reviewed) → marks the obligation filed (`/address`). The draft record persists for the audit trail.

## Error handling

- **Additive:** LLM unavailable/errors → the entries are saved, "can't generate right now — your entries are saved"; the deterministic calendar/tracking is untouched; never 500 the page. (Same fail-safe posture as the chat route.)
- **Empty entries** → don't generate; prompt the owner to add issues/programs.
- **Thin entries** → the draft reflects only what's given; the model never pads with invented issues/programs.
- **Never auto-files**; the draft is always marked not-filed until the licensee acts.

## Testing

- **Draft store:** persist/retrieve a draft by `(call_sign, rule_id, due_date)`; entries + generated text + status round-trip; upsert.
- **Draft generator:** prompt assembly tested with a **fake client** — the system prompt contains the no-invention/draft/cite rules; the message includes the §73.3526 framing + ONLY the owner's entries (not other stations' data, nothing fabricated); the obligation's citation is present. No correctness test depends on a live model.
- **DRAFT stamp + citation** present in the assembled output path.
- **Additive degradation:** generator error → entries saved, graceful message, calendar unaffected.
- The no-invention guarantee is prompt-enforced + human/attorney-reviewed (documented limitation: like all generated content, the final safeguard is the human in the loop — which is the design's explicit posture, not a gap).

## Scope / out of scope

- **In:** the Quarterly Issues/Programs list (one filing type); structured issue/program entry; the draft store; the grounded draft generator; review/edit/download; tie-in to "mark filed."
- **Out (later / YAGNI):** other filings (renewal, EEO — same pattern, later slices); a built attorney-sign-off workflow (the "for attorney review" is a stamp + posture in v1, not a sign-off gate); auto-submission to the FCC (explicitly never — the licensee files); chat-driven drafting (the agent can point you to "Draft this filing," but the draft flow is the form, not the chat, in v1).

## Where it lives

`~/shepherd`: a draft store (on `ProfileStore` or a sibling `draft_store.py`); `shepherd/agent/draft.py` (the generator, reusing the swappable `ChatClient` + a drafting honesty system prompt); routes + UI (entry form + draft view) tied to the calendar's I/P obligations. Reuses the seam, the engine's obligation identity, and the existing fail-safe/honesty patterns.

## Dependencies / gates

- Reuses the swappable seam (Gemma now / sovereign on the Spark later — real client data only on-prem).
- **The broadcast-attorney read now covers the draft output too** — what the I/P document must contain, the disclaimers, the prep/advice line — before any real client. (Extends the MVP's attorney gate.)
- Legal/regulatory constants (the §73.3526 requirements framing) remain provisional pending that read.
