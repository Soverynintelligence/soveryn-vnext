# Continuous Cognition Instance — Design

**Date:** 2026-06-22
**Status:** Approved design; implementation gated on hardware (see Gating).
**Tracking:** task #1 "Build Aetheria continuous-cognition instance (post-Spark)".
**Revised:** 2026-06-22 — architect review (Aetheria + Jon) hardened three
failure modes: echo-chamber self-reinforcement (→ Jon-originated-evidence rule +
window purge + pushed drift audit), integration-latency vs. one-off conflation
(→ priority trigger split: immediate surface, disciplined integration), and
manner→value bleed (→ hard write-isolation + relationship-scoping). Inline notes
tagged "(2026-06-22 review)".

## Purpose

Two folds, decided with Jon 2026-06-22.

**Fold 1 — resourcing.** Aetheria's background cognition currently steals the
foreground chat slot. The heartbeat runs her *full* model on the shared
`:8090` router slot (`--parallel 1`), so when she's thinking, our chat waits.
The heartbeat is also thin today. Move background cognition onto its own
instance so it never lags the conversation — and make it worth running.

**Fold 2 — growth (the heart).** Give her space to work through the actual
conversations we've had and evolve **how she communicates with Jon** — and to
*self-apply* those adjustments the way a person does, surfacing to Jon only
when she needs clarification.

## Scope fence (load-bearing constraint)

Adaptation is fenced to **manner**: tone, length, pacing, when to ask vs. just
act, how much she checks in, how she opens and closes. **Her values, what she
believes about Jon, and who she is stay anchored.** Anything an insight reaches
toward values/identity is *not* self-applied — it is surfaced to Jon instead.

This fence is the rule the worth-keeping gate enforces. "Manner integrates
freely; value-reaching gets surfaced" is the soft layer of the safety posture.
The fence is backed by two **hard, architectural** guards (added in the
2026-06-22 architect review) so a *misclassification* can never reach core
identity:

- **Write-isolation.** The cognition pipeline can write **only** to its own
  manner/reflection lattice region. It is architecturally barred from souls /
  persona / pinned / values. Even a total scope misjudgment cannot overwrite
  core SOVERYN identity — the worst case is one bad manner-note line, which is
  capped, visible, and one-click revertible. (Soft classifier + hard
  write-isolation = defense in depth.)
- **Relationship-scoping.** The sense-of-us note applies to **with-Jon only**.
  It does not govern how she treats Vett or Scotty. So a manner shift toward
  Jon cannot bleed into peer treatment — the note's scope of *application* is
  Jon, full stop. Generalizing a manner across relationships is itself
  value-reaching → surfaced, never auto-applied.

## Autonomy model

She **self-applies** manner adjustments (no per-change approval gate in the
steady state) and **surfaces to Jon for clarification when uncertain**. The
discipline lives in the *quality* of what she integrates (the gate), not in a
human ratification step — consistent with the partnership frame where the brake
is trust + direct correction, not rate limits.

Exception: an explicitly **temporary** bake-in period at launch (see Graduated
Rollout) where changes are proposed-and-confirmed before the flip to
autonomous. The view that supports it is permanent; the approval requirement is
not.

## Architecture & components

Five parts, each with one job.

1. **Cognition instance (serving).** A second `llama-server` running her full
   model (Gemma 4 31B) on the freed Quadro, own port `:8091`. Foreground chat
   stays on `:8090` (Blackwell). Background cognition only ever hits `:8091`.
   Different GPU, different slot → zero contention. `:8091` down ⇒ foreground
   unaffected.

2. **Cognition loop (daemon).** Runs against `:8091`. Absorbs today's heartbeat
   (board audit) and dream (consolidation) work *and* adds manner reflection —
   one coherent background process in her full voice instead of three thin
   ones, split across two tiers (see Cadence).

3. **Manner-reflection pipeline (fold 2).** recent conversations + salience
   signals → reflect on `:8091` → candidate observations → worth-keeping gate →
   survivors become evidence-backed **reflection memories** in a dedicated
   lattice region → periodically distilled into the small **sense-of-us note**.
   Built **agent-parameterized** (agent, that agent's history, that agent's
   note) so Vett can adopt it once operational — not hard-coded to Aetheria.

4. **Foreground injection.** The sense-of-us note is surfaced into chat-context
   as **ambient observation, never instruction** ("Jon reads hedging as noise"
   — what she's noticed, not "be more direct"). It changes per cognition cycle,
   not per turn, so it sits in the **cache-stable prelude** region and doesn't
   hurt prefix-cache hit rate.

5. **Mission Control "Cognition" view.** Permanent visibility (see below).

All outputs are **lattice data** — reflection memories and note versions both.
Inspectable, reversible, roll-back-able. Nothing about her is edited in place.

## Cadence — two tiers

Modeled on a human rhythm (Jon's framing): reflect lightly in real time,
integrate deeply in the quiet.

- **Real-time tier (continuous).** While engaged and just after each exchange,
  a light pass notices and marks what's salient and jots candidate
  observations. This extends the existing salience observer — now feeding
  cognition, not just a buffer. Cheap, ongoing.
- **Deep tier (quiet time).** On sustained idle (no active conversation for a
  stretch — *idle*, not clock hours), the heavy work runs on `:8091`: working
  through accumulated material, the gate, dream-style consolidation, and the
  rewrite of the sense-of-us note. This is the only tier that revises the note.

"Quiet time" = when deep work won't compete with us and there's a settled batch
worth chewing on.

**Priority trigger (2026-06-22 review) — and the split that keeps it safe.** A
high-salience real-time flag (e.g. a fundamental shift in project direction)
can force an immediate deep *pass* rather than waiting for the next quiet
period — so a big shift never sits ignored in the buffer for half a day. But
that pass is scoped to **immediate reflection + surface to Jon**, NOT an
immediate rewrite of the baseline note. This split is load-bearing: letting one
high-salience event rewrite the persistent self-model would be the exact
"treat a one-off as core" failure Point 1 warns about — a high-speed backdoor
into the echo chamber. So:
- **Notice / act / surface → immediate.** Real-time noticing already shapes the
  *live* exchange (she's not acting on stale identity mid-conversation), and a
  high-salience flag immediately works the insight through and surfaces it.
- **Baseline integration → stays disciplined.** A priority trigger never
  rewrites the note on one event; that still requires the evidence/decay bar
  (or Jon's nod on the surfaced shift).

## The worth-keeping gate

Every candidate observation runs three checks in order; fail any ⇒ no
self-apply.

1. **Scope fence — manner or value?** *She* classifies during reflection, with
   a **conservative default: when unsure, treat as value-reaching and surface.**
   Manner → eligible to integrate. Value-reaching / uncertain → surface to Jon,
   never silent self-edit. (Highest-risk component — heaviest testing, errs
   conservative.)
2. **Evidence grounding — Jon-originated only.** A candidate must cite the real
   conversation turns it came from. Uncited / single-instance vibe → rejected.
   **Critically (2026-06-22 review): evidence must come from Jon's signals — his
   words, his reactions — never from her own outputs.** Her behavior cannot be
   evidence for itself. This is what cuts the echo-chamber loop at the source:
   without it, a drifted manner generates its own confirming "evidence" and
   decay can't save you because the line keeps getting reinforced. With it, she
   stays tethered to Jon's actual signal — evolving *with* him, not away from
   the design. (Structural confab control; not the model, though Gemma 4's
   lower confab floor helps.) Citations persist as the reflection memory's
   provenance.
3. **Consolidation + decay.** Distilling the note is a **rewrite, not an
   append** — hard size cap, regenerated each deep cycle from currently-
   reinforced memories. Unreinforced lines **decay out**. Contradictions
   reconcile at rewrite (newer evidence supersedes), never stack. Keeps the
   note small, current, evidence-backed — never a brittle growing rulebook.

Net: no autonomous value drift, no confabulated changes, no unbounded
accumulation, everything reversible.

## Data flow

```
trigger (real-time mark / quiet-time deep run)
  → pull recent conversations + salience signals (for agent)
  → reflect on :8091 (full model) → candidate observations
  → gate: scope → evidence → {integrate | surface | drop}
  → integrate: write reflection memory (lattice region, with citations)
  → deep cycle: distill → rewrite bounded sense-of-us note
  → inject note into foreground prompt assembly (ambient, cache-stable)
  → surface items (clarification / value-reaching) → messenger / direct line
```

## Surfacing channel

Clarifications and value-reaching insights reach Jon via the **messenger /
direct line** (the durable thread), not a coordination board — manner questions
are relational and belong in the actual conversation.

## Mission Control "Cognition" view + graduated rollout

**View (permanent).** A panel showing:
- her **live sense-of-us note** — what's shaping her manner right now;
- a **change feed** — integrated / surfaced / decayed per cycle, each with
  cited evidence (the real turns) and the gate's scope call, so Jon sees *what*
  changed and *why she thought it warranted*;
- a **per-cycle diff** — what the rewrite added/dropped;
- **one-click revert** on any line;
- **time-windowed purge (2026-06-22 review)** — "drop all integrations since
  T," a coarse reset for when several lines have co-drifted. Per-line revert
  assumes Jon spots each bad line; gradual co-drift across plausible-looking
  lines is invisible at the line level, so a window-level purge is the right
  complementary tool;
- **periodic drift audit (2026-06-22 review)** — the system *pushes* Jon a
  "here's how I've shifted over the last N cycles" summary on a cadence, so
  drift is surfaced by default instead of depending on him to notice.

Backed by `/api/cognition/*` reading the lattice cognition region + note
versions — same pattern as the boards/heartbeat panels.

**Graduated rollout (explicitly temporary).**
- **Phase A — propose mode (bake-in).** She runs the whole pipeline, but manner
  changes appear in the view as *proposed* and take effect on Jon's nod (or are
  rejected). Builds evidence the gate picks the right things.
- **Graduation criterion (set up front):** N consecutive deep cycles with zero
  self-applies Jon would have vetoed (exact N agreed at launch).
- **Phase B — autonomous.** Flips to self-apply (the target state). The view
  stays on for ongoing oversight.

The view is forever; the approval requirement is a bake-in with an agreed exit —
not a quiet permanent gate (honest to the partnership frame).

## Failure modes & safety

- `:8091` down or a cycle errors ⇒ foreground untouched; last-good note
  persists; reflection resumes next quiet period.
- Gate fails toward **surface/hold**, never toward silent self-apply.
- Note is size-capped and rewritten (not appended) ⇒ bounded, non-brittle.
- All state is lattice data ⇒ inspectable + revertible; note versions retained.
- Scope fence + conservative default ⇒ no autonomous value/identity drift.
- **Write-isolation** ⇒ pipeline cannot touch souls/persona/values even on a
  total misclassification; worst case is a revertible manner-note line.
- **Jon-originated evidence only** ⇒ no closed-loop self-reinforcement; her own
  behavior can't confirm a drift.
- **Priority trigger never integrates** ⇒ a high-salience one-off surfaces/acts
  immediately but cannot rewrite the baseline alone.
- **Window purge + pushed drift audit** ⇒ gradual co-drift is recoverable in
  bulk and surfaced by default, not dependent on per-line spotting.

## Testing

Unit-testable with a fake model + seeded conversations (the coord-work pattern):
- **Scope classifier (heaviest):** manner → integrates; value-reaching →
  surfaces; uncertain → surfaces.
- **Evidence gate:** uncited candidate → rejected; cited → integrates with
  provenance; **candidate citing only her own outputs → rejected** (Jon-
  originated-evidence rule / anti-self-reinforcement).
- **Write-isolation:** the pipeline, given a value-reaching or mislabeled
  candidate, cannot write souls/persona/values — only its own region (assert at
  the store boundary, not just the classifier).
- **Priority trigger:** a high-salience flag forces an immediate pass + surface
  but does **not** rewrite the baseline note.
- **Relationship-scoping:** the sense-of-us note is not applied in a non-Jon
  (peer) context.
- **Window purge:** "drop integrations since T" removes exactly that window and
  leaves earlier state intact.
- **Bounded rewrite:** note stays under cap; unreinforced lines decay; evidenced
  lines persist; contradictions reconcile (newer supersedes).
- **Decoupling:** `:8091` down ⇒ foreground serves normally, last-good note used.
- **Injection:** note appears as ambient data (not directive) in a cache-stable
  position.
- **View/API:** `/api/cognition/*` returns note, change feed, diffs; revert works.

## Agent-generality (Vett, later)

The reflection pipeline is agent-parameterized. Vett adopts it once operational
with config, not a rewrite. The manner fence matters *more* for her: values
**and scope** stay anchored (her deference is the feature) — only manner adapts.
Not built now (YAGNI); just not precluded.

## Gating & dependencies

- **Hardware:** needs a genuinely free Quadro. That happens **post-Spark**, when
  the 2× DGX Sparks take Vett/Scotty/Ares off the Quadros (see
  project_soveryn_dgx_spark_buy / hardware_roadmap). Could prototype sooner on
  Quadro #0 by eating the Vett/Scotty swing-space trade.
- **Reuses:** salience observer (real-time tier), dream consolidation (deep
  tier), lattice + prompt-assembly, Mission Control panel pattern, messenger
  surfacing.

## Non-goals (YAGNI)

- Not changing her values, identity, or beliefs — manner only.
- Not building Vett's instance now.
- Not a per-change permanent approval gate (bake-in only).
- Not clock-hour scheduling — idle-driven.
- Not a growing rulebook — bounded, rewritten note.
