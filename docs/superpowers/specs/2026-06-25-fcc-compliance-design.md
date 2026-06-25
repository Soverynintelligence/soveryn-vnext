# FCC Compliance Tool — Design (MVP / Slice 1)

**Date:** 2026-06-25
**Status:** Approved design (brainstormed + endorsed). MVP / first slice of a multi-slice product.
**Concept:** A sovereign FCC regulatory-compliance tool for small/mid-market radio stations. It computes and tracks every fine-triggering deadline, alerts the owner across channels, and (phase 2) drafts the filings — all grounded in the actual CFR with citations, all reviewed and filed by the licensee. Cloud-testable now; deploys sovereign on a DGX Spark (the 2-owners → 2-Sparks proof vehicle).
**Prior context:** memory `project_soveryn_fcc_compliance_opportunity` (verified fine bases, obligations, UPL analysis); Vett's Blueprint spec; the UPL/liability library node.

## Purpose & value

The value is **avoided fines**, not "attorney savings" (no defensible cost-savings number survived verification). Real fine bases (47 CFR §1.80): public file / Quarterly Issues-Programs lists **$10,000**; political file **$9,000**; late filing **$3,000**; a real **$25,000** consent decree (Feb 2025) for exactly the miss-a-deadline failure mode. With the tool: **$0**.

Success metric is **never miss a fine-triggering deadline + every assertion cited** — NOT an accuracy percentage (a % is dangerous framing for a legal/compliance tool).

## The UPL / liability spine (non-negotiable, shapes everything)

This is a **prep / organize / draft / track TOOL the licensee reviews and files.** It provides legal *information* (cited explanations of the rules) and drafting, never legal *advice*, and never "we file for you." Every regulatory assertion **cites its CFR section** for one-click human verification (the SOVERYN provenance edge). Sovereign on-prem ownership reinforces the boundary (their data, their tool, their filing). **A broadcast attorney's read is a hard gate before the tool touches a real client** — but not before we build/test the engine.

## The deterministic law (architectural, not behavioral)

**The deadline engine is pure deterministic code; the LLM is structurally excluded from the date path entirely.** A date is *computed and cited*, never *generated* — so the model cannot lie about a deadline because it never produces one (same discipline as the cognition write-isolation). The risk shifts from "model hallucinated a date" (probabilistic) to "we encoded a rule wrong" (a code bug — testable, citable to the exact CFR text, attorney-reviewable). That trade is the whole point.

## Scope

**MVP (this spec):** deterministic deadline engine + declarative CFR rule definitions + station profile + multi-channel notification layer + a basic UI. Needs **no LLM** — buildable and cloud-testable immediately.

**Out of scope (later slices / YAGNI):** the generative layer (cited regs Q&A + paralegal drafting — phase 2, on the swappable brain); the Spark/sovereign deployment (cloud-test the engine first); multi-station-group management; billing; the AI-political-ad disclosure rule (still an NPRM, not effective).

## Architecture & components

A small standalone compliance service + basic UI + notification delivery. Reuses SOVERYN's delivery rails (Signal/SMS, email, messenger) and, in phase 2, the proven swappable-brain seam.

1. **Station profile store** — per-station inputs that drive the engine: call sign, service (AM/FM), community of license, license expiration date, market/state. Simple SQLite store; entered via the UI. The required-fields contract is explicit so the engine can refuse to compute when data is missing.
2. **Rule definitions (declarative)** — the CFR obligations encoded as inspectable data, NOT hardcoded logic. Each rule: `{id, cfr_citation, description, recurrence (how the due dates are computed), alert_lead_times}`. Declarative so the rules are citable, attorney-reviewable, testable, and extensible by editing data. Seed set: Quarterly Issues/Programs lists (§73.3526, due Jan/Apr/Jul/Oct 10), license renewal window (§73.3539), political-file windows (§73.1943), EEO (§73.2080).
3. **Deadline engine** — pure deterministic function: `(profile, rules) → schedule of upcoming obligation instances, each with an exact due date and its CFR citation`. No LLM. Deterministic and fully unit-testable.
4. **Notification layer** — watches the computed schedule; fires **escalating multi-channel alerts** (e.g. 30 / 14 / 3 / 1-day lead) over email / SMS / Signal / messenger, reusing SOVERYN delivery. Records sent + acknowledged; escalates channel on non-acknowledgment/delivery failure.
5. **Basic UI** — the station's compliance calendar (obligation, due date, status, **CFR citation per item**), the profile form, alert settings. Deliberately minimal — the value is the alerts + cited items, not a slick app. Multi-surface reach (laptop/mobile) via the notification rails + a simple web view.
6. **(Phase 2) Generative layer — document drafting/generation + cited regs Q&A.** The headline "paralegal" capability. Driven by the engine: for a computed obligation, fill **its** FCC-standard template/form with the station's profile + provided facts → a **DRAFT document** the licensee reviews, edits, and files. Every generated doc: carries its CFR citation(s), is stamped **"DRAFT — for licensee review,"** and is **never auto-filed or auto-submitted.** This is document *preparation* (paralegal filling a form), not legal advice — the attorney read must bound *which* documents are safe to auto-draft, the required disclaimers, and the prep/advice line. Also: cited regs Q&A ("what does §X require?" → answer + citation). Runs on the swappable brain (cloud-test on public regs + sample data / sovereign Spark for real client data). Out of MVP, but the immediate next phase built directly on the deadline engine.

## Data flow

profile entered (UI) → **deadline engine** computes the cited schedule → UI shows the compliance calendar → **notification layer** fires escalating alerts as each date approaches → owner acts/acknowledges → *(phase 2)* owner asks "what does this obligation need?" → brain answers with citation / drafts the filing → owner reviews & files.

## Error handling (the "never lie" edges)

- Missing/unknown profile data → engine **flags "cannot compute X without Y" and emits no date** — never guesses.
- Rule ambiguity → surface the obligation with its CFR citation and flag for human judgment; do not auto-resolve.
- Notification delivery failure → retry, then escalate to another channel; never silently drop a deadline alert.
- The engine **never emits an uncited date, or a date computed from incomplete data.**

## Testing — the rigor center

- **Golden tests per obligation:** `(station profile) → expected due dates + CFR citation`, verified against the actual CFR text and confirmed in the attorney read. This is where correctness lives.
- Notification: lead-time + escalation + delivery-failure-fallback tests.
- Profile-incomplete → flagged-not-guessed tests.
- Determinism: same profile → identical schedule, every run.

## Cloud-test-now / portable / Spark-later

The MVP (engine + notifications + UI) uses no LLM, so it builds and tests immediately on any machine. Phase-2 generative work uses the swappable-brain seam (`spike/swappable-brain`): cloud (OpenRouter, public CFR + sample station data only) for testing, sovereign local model on the Spark for production. **Real client confidential data only ever runs on the local Spark** — that's the sovereignty promise; cloud testing uses public rules + sample/fake station data.

## Dependencies & open items

- Reuses: SOVERYN delivery rails (Signal/SMS, email, messenger); phase-2 swappable seam.
- **Gate:** broadcast-attorney review of the encoded rules + the UPL framing before any real client.
- Open (decide at plan/build time): the exact declarative rule schema; the seed rule set's precise date math (verify each against the CFR); which channels for MVP alerts (email + SMS likely first); the basic-UI tech (could be a minimal web view reusing the SOVERYN app shell, or standalone — plan-time call); own repo vs. inside the SOVERYN tree.
- **De-risk before commit (from the prior assessment):** confirm the two owners will actually pay/commit; get the real $/yr they currently spend (for pricing); lock the appliance economics (Spark + subscription, not $500/yr SaaS).
