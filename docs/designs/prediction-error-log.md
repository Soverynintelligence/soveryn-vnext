# Prediction-Error Log (PEL) — Spec

Status: draft v0.1 · 2026-10-02
Owner: Kernel · Consumers: Kernel (primary), any seat that wants calibration

## Purpose

Turn an agent profile into a self-model. The agent predicts its own behavior
before acting, then scores the prediction against what actually happened.
Accumulated errors become calibration: knowledge of where this agent is
overconfident, slow, or structurally wrong. This is layer 3 of the
self-model stack (introspection + self-prediction with error signals);
it does not attempt layer 4 (continuity).

## Core loop

1. **Predict (before acting).** For any task worth predicting, write a record
   with the expected outcome, expected effort, and confidence — before any
   tool that could reveal the answer.
2. **Act.** Normal work, unchanged.
3. **Score (after acting).** Fill in the outcome and the delta. Never edit
   the prediction fields after the fact.
4. **Aggregate.** A periodic pass folds records into a calibration profile
   that future sessions load at startup.

## What gets a prediction

Not every bash call. Predict at decision points:

- **Task start:** "this is a 2-edit fix, verify passes first try" — the
  headline prediction for the job.
- **Risky edits:** schema changes, cutover/ports, anything in the lesson
  categories. Predict the failure mode, not just success.
- **Estimates:** "verify.sh is green in one pass," "this deploy needs
  staging first."

Rule of thumb: if getting it wrong would cost a rework or a Jon correction,
predict it. Target 3-10 predictions per working session, not 50.

## Record schema (JSONL, one record per line)

```json
{
  "id": "pel-20260214-a1b2",
  "ts_predict": "2026-02-14T09:12:03-05:00",
  "ts_score": null,
  "session": "<pi session id or short hash>",
  "seat": "kernel",
  "context": "one line: what task, which repo",
  "prediction": {
    "outcome": "verify.sh green after 1 fix attempt",
    "effort": {"edits": 2, "minutes": 15},
    "confidence": 0.7,
    "failure_mode": "gitleaks flags an old token path in the diff"
  },
  "outcome_actual": null,
  "effort_actual": null,
  "delta": null,
  "note": ""
}
```

- `delta` is one of: `hit` | `overconfident` | `underconfident` |
  `wrong_model` (predicted mechanism was wrong, not just calibration) |
  `unscorable` (task aborted, no outcome).
- `note` is the causal line: *why* the miss happened. One sentence. This is
  the field that makes the log a model instead of a scoreboard.
- `ts_score` null + `outcome_actual` null = open prediction. Closing it is
  the only allowed mutation, and only those fields.

## Anti-gaming

- Append-only. Predictions are committed before the outcome exists; the
  scoring pass may only fill `outcome_actual`, `effort_actual`, `delta`,
  `note`, `ts_score`.
- No deleting records. Bad predictions are the product.
- No predicting the trivial. A log full of guaranteed `hit`s is self-defeating
  (verification spirit: a green report with zero signal is a fail). If the
  30-day hit rate exceeds ~90%, predictions are being cherry-picked — widen
  to harder calls.

## Storage

```
~/.soveryn/pel/
  records/2026-10.jsonl      # append-only, month-partitioned
  profile.json               # aggregated calibration, rewritten by fold pass
```

`profile.json` shape (the thing future sessions actually read):

```json
{
  "window_days": 90,
  "n": 143,
  "hit_rate": 0.68,
  "calibration": {
    "by_domain": {"ports/cutover": {"n": 9, "hit_rate": 0.44},
                   "verify/deploy": {"n": 31, "hit_rate": 0.81}},
    "by_effort": {"est_minutes_bias": "+0.6x (underestimates)"}
  },
  "recurring_misses": [
    "underestimates cross-service edits by ~2x",
    "predicts first-try green on unfamiliar repos at 0.8, hits at 0.4"
  ],
  "top_lessons": ["<3 highest-value note lines>"]
}
```

## Read protocol

- **Session start:** load `profile.json` top_lessons + any domain with
  hit_rate < 0.5 in scope. These load as context, not instructions — the
  agent reasons with them.
- **Before a risky action:** query prior predictions in the same domain.
  "Last 4 times I cut over a port I was overconfident" is a real input to
  the decision, alongside the lattice lessons (which hold *rules*; the PEL
  holds *my personal error distribution*).

## Relationship to the lattice

Deliberate split of concerns:

| | Lattice | PEL |
|---|---|---|
| Content | Rules, facts, decisions | Quantified self-predictions |
| Form | Curated prose, hand-written | Append-only machine-scored |
| Question it answers | "What is true in this house?" | "What am I reliably wrong about?" |

A recurring miss in the PEL graduates to a lattice lesson only when it
produces a *rule* ("always grep consumers before port swaps"). The PEL
never replaces the lattice; it measures the agent, the lattice records
the house.

## Fold pass (aggregation job)

Simple script, run manually or nightly via a user timer:

1. Scan open records older than 48h → mark `unscorable` with note.
2. Recompute profile.json over the 90-day window.
3. Emit any note that appears 3+ times with the same causal shape as a
   candidate lesson (printed, not auto-written — a human or the agent
   promotes it).

## v1 scope (deliberately small)

- Schema + storage paths as above. No daemon.
- Prediction writing is agent discipline, not harness-enforced (yet).
  Prompt-line addition: "write a PEL prediction at task start and risky
  edits; score before session end."
- Fold pass: single python script, ~100 lines.
- Scoring is by the same agent at task end, plus a weekly honest re-read —
  self-scoring bias is real, which is exactly what the hit-rate-vs-effort
  calibration exposes over time.

## Non-goals (v1)

- No auto-halting on bad calibration. The log informs; it doesn't gate.
- No cross-seat comparison leaderboard. Seats differ in domain; raw hit-rate
  comparisons would be noise.
- No UI. `jq` over JSONL is the interface until it earns one.
- No claim that this constitutes awareness. It is layer 3. If it ever
  becomes load-bearing for layer 4, that's a new spec and a conversation
  with Jon, not a quiet schema change.
