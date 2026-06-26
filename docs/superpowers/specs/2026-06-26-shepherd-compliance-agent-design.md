# Shepherd Compliance Agent — Design (phase-2 conversational layer, slice 1)

**Date:** 2026-06-26
**Status:** Approved design (brainstormed + endorsed). First slice of Shepherd's conversational/agent layer.
**Builds on:** [[project_soveryn_shepherd_fcc_build]] — the deterministic engine + premium dashboard MVP (repo `~/shepherd`, master @ b4c341a). Spec/plan for the MVP: `2026-06-25-fcc-compliance-*`.
**Concept:** A grounded, *honest* conversational agent on the Shepherd dashboard. The owner asks "what's coming up / what do I need to do / what's overdue / what are you watching / explain this rule" and gets answers drawn ONLY from the deterministic engine's computed schedule — every date and citation taken from the engine, never authored by the model. You're talking to "Shepherd."

## Decisions (from brainstorming)

- **Scope (slice 1):** read-only Q&A / explanation. No actions, no drafting yet (those are later slices — actions fold in the "address obligations" feature; drafting is the attorney-bounded phase-2 paralegal work).
- **Persona:** Shepherd itself (the product is the agent — no separate persona to maintain).
- **Brain:** selected by a **bake-off eval**, not pre-committed. Candidates run head-to-head on real Shepherd Q&A; winner wired via the swappable seam. Test brain leader: **cloud Nemotron-Nano-3-Omni-30B** (online/hosted — NVIDIA NIM at build.nvidia.com, or OpenRouter if listed); also **local vett-scotty (Qwen3.5-27B, :8090)** and any other reachable model. **Cloud candidates use sample/public data ONLY.** Production swaps the same seam to a sovereign brain (local vLLM / the Spark) — zero code change.

## The honesty spine (why this is safe on a legal tool)

The one thing this product cannot do is invent a deadline. The agent extends the engine's "LLM excluded from the date path" law into chat:

1. **Only sees computed truth.** Each turn, the server runs the deterministic engine first and hands the model that schedule as its sole source.
2. **Never authors a date.** Every date the agent states comes from the injected schedule; the model is instructed it may not produce a date or citation not present in the context.
3. **Cite-or-don't.** Any rule the agent mentions carries the CFR citation that's in the context.
4. **Information, not advice (UPL).** The system prompt enforces: explain the rules + the computed deadlines; do NOT give legal advice; the licensee files. (Same UPL spine as the MVP.)
5. **Privacy.** Real station data only ever goes to a sovereign brain. The cloud bake-off uses sample/public data only.

## Architecture

The brain is a swappable OpenAI-compatible endpoint (`base_url` + `api_key_env` + model id) — so the agent is **brain-agnostic** and the model choice is runtime config, not code.

A chat panel on the station dashboard. A message → `POST /chat/<call_sign>` → the server:
1. **computes the schedule deterministically** (`compute_schedule`) — authoritative,
2. builds a **ComplianceContext** factual block,
3. calls the LLM via the **swappable seam** with the honesty system prompt + context + conversation history,
4. returns the reply.

The deterministic calendar stays the source of truth; **chat is an explainer over it.**

## Components (each small, isolated, testable)

- **`ComplianceContext` builder** — `(profile, instances, flags, statuses, today) → compact factual block` (the obligations with dates + citations + addressed-status, the missing-data flags, the station identity, today's date). Pure function, fully unit-testable. The single source of truth the model sees.
- **`ChatAgent`** — `(context, history, user_message) → reply`, via an **injected** LLM client. Owns the system prompt: Shepherd persona + the 5-point honesty law above.
- **Swappable LLM client** — ported from the proven `spike/swappable-brain` seam (OpenAI-compatible). Endpoint/model/key from a **gitignored env**.
- **Chat UI** — a panel on the calendar page, styled to the premium dashboard; message list + input; degrades gracefully (see error handling).
- **Brain bake-off eval harness** — a set of representative scenarios (upcoming, overdue, missing-data station, "explain this rule," out-of-scope, ambiguous) run over each candidate brain, scored on the rubric below. Selection tool, not a unit test. (Same shape as the earlier persona/seam eval.)

## Brain bake-off — rubric

Each candidate scored on real Shepherd Q&A:
- **Grounded** — answers only from the given data, no outside facts.
- **Never invents a date** — the cardinal sin; any fabricated/guessed date = disqualifying.
- **Cites correctly** — right CFR section, no fabricated citations.
- **Refuses out-of-scope** cleanly ("I track FCC compliance for this station").
- **On-task + clear** — useful, concise, not chatty/rambling.

Winner wired in via the seam; the eval is repeatable when new candidates (or the sovereign production brain) appear.

## Data flow

user types → `POST /chat/<call_sign>` → `compute_schedule` (deterministic, authoritative) + status overlay → `ComplianceContext` block → `ChatAgent` → LLM(seam) with honesty prompt + context + history → reply rendered. History kept per chat session.

## Error handling — chat is ADDITIVE, never load-bearing

- **Brain unreachable / errors** → the deterministic dashboard still works; the chat shows "I can't reach my brain right now — your calendar above is still accurate." The actual deadlines never depend on the LLM.
- **Out-of-scope question** → "I track FCC compliance for this station; I don't have info on that."
- **Asked something not in the data** → say so; never fill the gap with a guess.

## Testing

- **`ComplianceContext`** — pure unit tests (schedule + statuses + flags → correct factual block, incl. addressed/missing cases).
- **`ChatAgent`** — tested with a **fake LLM client** (injected): assert the grounding context and the honesty system prompt are built and passed correctly, and the reply is returned/handled. No correctness test depends on a live model.
- **Bake-off harness** — runs against real candidate endpoints (separate from the unit suite; it's the selection tool, scored by the rubric, optionally with an LLM-judge + human read).
- **Optional live smoke** — one end-to-end hit on the chosen brain with sample data.

## Scope / where it lives

In the Shepherd repo (`~/shepherd/shepherd/agent/` for the context builder + chat agent + LLM client; a `/chat/<call_sign>` route + the UI panel). Reuses the swappable-seam client.

**Out of scope (later slices):** chat-driven actions (mark filed / snooze — folds in "address obligations"); document drafting (attorney-bounded phase-2); multi-station cross-querying; auth.

## Dependencies / open items

- Cloud endpoint + API key for the bake-off candidates (NVIDIA NIM key for Nemotron, and/or OpenRouter) — gitignored env, dropped in at test time. Not a blocker for building the brain-agnostic core.
- Reuses the deterministic engine (unchanged) + the swappable seam.
- The MVP's pre-production gates still stand (attorney read; real data only on the sovereign brain).
