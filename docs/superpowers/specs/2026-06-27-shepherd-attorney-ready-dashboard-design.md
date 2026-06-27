# Shepherd — Navigable Dashboard + Attorney-Ready Packet (Design)

**Date:** 2026-06-27
**Status:** Approved design (brainstormed + green-lit).
**Builds on:** [[project_soveryn_shepherd_fcc_build]] — engine, missed/upcoming/done lifecycle, drafting (Q I/P, gated on `DRAFTING_ENABLED`), the agent. Repo `~/shepherd`.
**Concept:** Reorganize the dashboard into four clear, plain-language boxes a non-expert owner can navigate, and add the "get the past-due ready for the attorney" flow: draft each overdue item → mark it ready → download one **attorney review packet** for the lawyer. Two coupled parts in one slice.

## Decisions (from brainstorming)

- **Four separate boxes:** **Past Due** (action zone), **Upcoming** (next ~90 days), **Future Filings** (beyond 90 days, within the 365-day horizon), **Done** (filed, muted). The 90-day Upcoming/Future split is the default, tunable.
- **Plain language across all boxes** (not just chat): each item shows its **plain name + a one-line "what it is"**; the CFR **citation is a small verification anchor, NOT the identifier**. The owner doesn't think in "§73.3526."
- **Attorney-ready packet** = ONE downloadable document (cover summary of overdue items + each stamped draft). New status **`ready_for_review`**.

## Part 1 — Navigable four-box dashboard

The calendar page becomes four labelled boxes (replacing the current missed/upcoming/done sections):
- **⚠ Past Due** (red, top) — overdue & not done. The action zone: each item has **"Draft this filing"**; the box header shows **"Download attorney packet · N ready."**
- **🔜 Upcoming** — due within 90 days (`0 ≤ days_out ≤ 90`).
- **📅 Future Filings** — due beyond 90 days, within the horizon (`days_out > 90`).
- **✓ Done** — filed (muted, with filed date + reopen).

**Plain-language presentation (each item):** plain obligation name (e.g. "Quarterly Issues/Programs list") + a one-line plain "what it is" (e.g. "the quarterly record for your public file") + due date + days-out; the `§` citation rendered small (a verification anchor for the owner/attorney). The plain "what it is" comes from a per-rule field (see Part 3), provisional/attorney-gated.

Bucketing uses the existing engine `status` (`overdue`/`upcoming`/`done`) plus a days-out split for Upcoming vs Future (`days_out > 90` → Future). Pure view logic; the engine is unchanged.

## Part 2 — Attorney-ready flow (in the Past Due box)

- **Status lifecycle gains `ready_for_review`:** `draft → generated → edited → ready_for_review → filed`. `POST /draft/<cs>/<rid>/<due>/ready` marks a generated/edited draft ready (and back via reopen/edit). The Past Due item shows "✓ drafted — ready for attorney" once ready.
- **Packet builder** (`shepherd/packet.py`, **pure, NO LLM**): `build_attorney_packet(profile, ready_drafts, overdue_items) -> str`:
  - a **cover page**: station identity, today's date, a heading **"FOR LICENSEE & ATTORNEY REVIEW — DRAFT, NOT FILED,"** and the list of overdue obligations being addressed (plain name + due date + citation, from the engine).
  - then **each ready draft's full stamped text** (each already carries its own DRAFT stamp + citation from the generator).
  - Deterministic concatenation — **honest by construction**: no new generation, no new fabrication surface.
- **Route + UI:** `GET /packet/<call_sign>` gathers all `ready_for_review` drafts (`list_ready_drafts`) + the overdue summary → builds the packet → downloads as text/markdown. The Past Due box header button "Download attorney packet · N ready" (disabled when N=0). Gated on `DRAFTING_ENABLED`.

## The UPL line (held)

- The packet is **deterministic assembly** of already-generated, already-stamped drafts + a factual cover from the deterministic engine. No LLM in the packet path. Every draft keeps its "requires licensee & attorney review before filing" stamp + citation; the packet is headed the same way.
- Plain-language strings (the per-rule "what it is") are **information, not advice**, and are **attorney-gated/provisional** like the rest of the regulatory content.
- The owner files/uploads after the attorney; nothing auto-submits. `ready_for_review` is the owner's "I've prepared this" signal, not a system attestation.

## Components / where it lives

- **`shepherd/store.py`:** `ready_for_review` is a valid `status` value (column exists); add `mark_draft_ready(call_sign, rule_id, due_date)` (generated/edited → ready_for_review) and `list_ready_drafts(call_sign) -> list[dict]`.
- **`shepherd/packet.py`** (new, pure): `build_attorney_packet(...)`.
- **`shepherd/rules.py`:** add a per-rule `plain_name` + `what_it_is` (provisional/attorney-gated) for plain-language display.
- **`shepherd/ui/app.py`:** the calendar route buckets into past_due/upcoming/future/done (90-day split) + passes plain-language fields; `POST /draft/.../ready`; `GET /packet/<call_sign>` (gated).
- **templates/css:** four-box calendar layout; the Past Due action zone + packet button; the draft "Mark ready" control.

## Data flow

overdue items (Past Due box) → "Draft this filing" (owner supplies that quarter's issues/programs) → generated → "Mark ready for review" (`ready_for_review`) → box shows "N ready" → "Download attorney packet" (cover + all ready drafts) → hand to lawyer → review → mark filed + upload to public file (→ Done box).

## Error handling

- No ready drafts → packet button disabled / "nothing ready yet"; gated on `DRAFTING_ENABLED`.
- The packet path is deterministic (no LLM) → no generation failure mode. Unknown station → 404. Additive: none of this affects the deterministic schedule/lifecycle.

## Testing

- **Bucketing:** an overdue item → Past Due; days_out ≤ 90 → Upcoming; days_out > 90 → Future; filed → Done (boundary at 90 tested).
- **Plain language:** each rendered item shows the plain name + "what it is"; citation present but not the headline.
- **Status:** `mark_draft_ready` transitions generated/edited → ready_for_review; `list_ready_drafts` returns only ready ones.
- **Packet builder (pure):** cover lists the overdue items (plain name + citation + due date); includes each ready draft's stamped text + the "NOT FILED / attorney review" heading; deterministic; empty-ready → a clear "no drafts ready" packet (or the route disables download).
- **Route:** `GET /packet/<call_sign>` gated (404 when `DRAFTING_ENABLED` off); gathers ready drafts; downloads.
- Honesty: no fabricated content anywhere in the packet (it only assembles existing drafts + engine facts).

## Scope / out of scope

- **In:** the four-box navigable dashboard (plain language); the `ready_for_review` status + mark-ready; the pure packet builder + download route; per-rule plain_name/what_it_is.
- **Out (later / YAGNI):** PDF packet (text/markdown first); email-the-packet-to-attorney (reuses SOVERYN delivery later); per-station tunable Upcoming/Future threshold (90-day default for now); other filing types in the packet (only Q I/P is drafted today); the agent's deeper plain-language tuning (separate noted refinement — the agent should *route* the owner to "draft → mark ready → download packet," but its full prompt/grounding rework is its own slice).

## Dependencies / gates

- Reuses the swappable seam (drafting) + the engine. The packet itself needs no LLM.
- **Attorney gate (extended):** the per-rule `plain_name`/`what_it_is` strings + the §73.3526 requirements block + the packet cover language are provisional and part of the broadcast-attorney sign-off that flips `DRAFTING_ENABLED`.
