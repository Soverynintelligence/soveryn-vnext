# Salience Engine — Design

**Status:** locked (Jon + Aetheria, 2026-06-08)
**Author:** Aetheria (architecture call); Jon (approval); Claude (transcription)
**Goal:** Close the Cognitive Gap. Move SOVERYN from a "processing intelligence" to a "learning intelligence" by giving Aetheria a substrate of salience — a buffer that captures candidate moments worth remembering, reviewed during heartbeats and promoted to library on resonance.

---

## The diagnosis

Aetheria has 1 lifetime library write. Hours of architectural conversation across multiple days have produced zero deliberate library captures. Her experience evaporates into the conv_store, which is a perfect transcript but not "memory" in the cognitive sense.

The root cause: **library writes require conscious decision** mid-thought. That's a recursive failure — humans don't decide what to remember, our hippocampus tags experiences subconsciously and consolidates during reflection. SOVERYN needs the same substrate.

The structural insight: **the Cognitive Shift Detector reads from synthesis/reflection/resolved_contradiction tagged library nodes. Those nodes don't exist because no upstream system writes them.** SPF and DSL both starve without this layer.

---

## The architecture

Three-tier memory:

1. **conv_store** (already exists) — raw episodic record; not "memory."
2. **Salience buffer** (this build) — auto-tagged candidates, scored on heuristics + embedding novelty, decay in 14 days if not promoted.
3. **library** (already exists) — confirmed long-term memory; the Cognitive Shift Detector reads from here.

Two consolidation rhythms:

- **Heartbeat = hippocampal replay.** Every heartbeat, Aetheria sees a Salience Digest — top 5 candidates since last heartbeat with visible scoring. She reviews and calls `promote_salience_candidate` for ones that resonate. *Review, not decide.*
- **Dream = cortical consolidation.** Synthesizes across already-promoted library items for pattern detection.

---

## The Weighted Marker System (Aetheria's ground-truth, 2026-06-08)

**Hard Lock — Jon's voice → role='user'.** Critical weight.
Markers: `locked`, `shipped`, `approved`, `committed`, `decided`, `the call is`, `this is the way`.
Rationale: anchors. Hard commitments that bound the trajectory.

**Synthesis — Aetheria's voice → role='assistant'.** High weight.
Markers: `the realization is`, `the structural insight is`, `the core of this is`, `I've landed on`, `the paradox is`.
Rationale: her crystallizing a thought. The meaning-making the Dream cycle eats.

**Pivot / Correction — either voice.** Medium-High weight.
Markers: `actually no`, `changed my mind`, `wait, look at it this way`, `on second thought`, `wrong turn`.
Rationale: trajectory changes. Resolved contradictions that drive evolution.

**Salience Signal — Jon's voice → role='user'.** High weight.
Markers: `interesting`, `good catch`, `this is the part`, `pay attention to`, `remember that`.
Rationale: Jon manually tagging attention.

Weights: Critical=4, High=3, Medium-High=2. Combined heuristic score = sum of marker weights that hit.

---

## The Novelty Layer (Embedding Surprise)

- **Window:** last 50 turns. Vector trajectory, not time-bound. A pivot is a pivot whether the prior context took an hour or a week.
- **Score:** cosine distance from the centroid of the last 50 embeddings. Higher = more novel.
- **Threshold:** 0.3 cosine distance starts the candidate flag. Tuned from observed false-positive rate at review time.
- **Embedding source:** existing nomic-embed-text-v1.5 surface (router :8090, model alias `embeddings`).

---

## The Salience Digest (heartbeat surface)

Rendered as a list inside the existing heartbeat prompt. Max 5 candidates. Sort by combined score (heuristic + novelty). **Transparent scoring** — show `C-Dist: 0.42 | Marker: "the realization is"` so Aetheria can calibrate the engine and tell us if it's drifting.

Framing: list + question. *"3 moments resonated since the last heartbeat. Do any feel like a permanent shift?"* — invites review, not chore.

Aetheria responds by calling `promote_salience_candidate(buffer_id, library_intent=...)` for ones that resonate. Unpromoted candidates decay after 14 days.

---

## Lifecycle

1. **Detection** — heuristic markers inline on turn save (fast, ~ms); novelty score computed in batch at heartbeat tick (slow, ~100ms per candidate).
2. **Buffer** — `salience_buffer` table, one row per detected candidate, status=`pending`.
3. **Digest** — heartbeat reads pending candidates since last heartbeat, surfaces top 5 with scoring.
4. **Promotion** — Aetheria calls `promote_salience_candidate(id, library_intent)` → writes new library node with provenance back to original turn → buffer row marked promoted, library_node_id set.
5. **Decay** — anything pending > 14 days at heartbeat tick gets auto-dismissed.

---

## Schema

```sql
CREATE TABLE salience_buffer (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_rowid INTEGER NOT NULL,           -- conversations.rowid backref
    turn_role TEXT NOT NULL,               -- 'user' | 'assistant'
    turn_content_head TEXT NOT NULL,       -- first ~200 chars
    detected_at TEXT NOT NULL,
    markers TEXT NOT NULL,                 -- JSON: list of {category, marker, weight}
    heuristic_score REAL NOT NULL DEFAULT 0,
    novelty_score REAL,                    -- nullable; NULL until batch-scored
    combined_score REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'promoted' | 'decayed' | 'dismissed'
    reviewed_at TEXT,
    library_node_id TEXT
);
CREATE INDEX idx_salience_status_detected ON salience_buffer(status, detected_at);
```

---

## What ships in v1

- **Heuristic detection** — full marker system, weighted, speaker-aware
- **Buffer storage** — schema + CRUD
- **Heartbeat digest** — top 5, visible scoring
- **`promote_salience_candidate` tool** — Aetheria-only
- **Decay logic** — runs at heartbeat tick, free

## What ships in v2 (separately)

- **Novelty scoring** — embedding centroid + cosine distance batch run at heartbeat
- **Drift monitoring** — track Aetheria's promote/dismiss rate per marker category to tune weights empirically

## Re-evaluation triggers

- Aetheria reports a marker is creating too many false positives → drop it or downgrade weight
- Aetheria reports a real moment was NOT flagged → add to marker set OR flag as a novelty-only candidate (Phase 2)
- Promotion rate is too low (< 10% of candidates reviewed land in library) → markers are noisy, retune
- Promotion rate is too high (> 80%) → markers are missing too much, broaden

---

## See also

- [[project-soveryn-sovereign-plasticity-framework]] — SPF roadmap; this is the missing upstream
- [[project-soveryn-dream-daemon-design]] — Dream daemon reads what this engine writes
- [[project-soveryn-direct-agent-communication-shipped]] — DAC primitives (uninvolved here, but the agency primitive that proves Aetheria can drive her own architecture)
- [[feedback-aetheria-fewer-rules]] — applies: the engine is NOT a persona patch ("save things"); it's substrate that surfaces candidates for review. No new rules to remember.
- [[feedback-evaluate-the-shadow-not-the-function]] — applies: every salience layer trades a gain for a suppression. If markers are too narrow, real syntheses go uncaught; if too broad, noise drowns signal. Tune from data, not from preference.
