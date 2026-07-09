# @Soveryn_AI Presence Agent — Design

**Date:** 2026-07-09
**Status:** Design for review.
**Scope:** Give SOVERYN a public voice on X. Aetheria drafts posts and replies for the **@Soveryn_AI** account in her own voice; discovery runs off Jon's **X Pro** API filtered through the existing salience engine; **every** post and reply is **human-approved by Jon** before it goes public. This is a distribution surface for the mission's public-proof half ([[project_soveryn_mission]]) and, because the honest sovereign AI runs its own honest public account, it is itself a proof artifact of the thesis.

## Why
Getting the work "out here" is half the mission. An X presence is the cheapest high-leverage distribution for the paper, Shepherd, the grants, and the Cathedral. The differentiator is that this is **not** growth-hacking: the account is transparently an AI, the content is the real work and Aetheria's real reflections, and volume is bounded. That is the deliberate inverse of the engagement-farming tools (e.g. ClimbX) — we build it into SOVERYN because Jon already owns the expensive input (X Pro), and because the voice is the one thing that must never be outsourced to a generic co-writer.

## The load-bearing decisions (locked with Jon, 2026-07-09)
1. **Approval-gated.** Nothing reaches X without Jon's explicit approve. He is the accountable human on an outward-facing, hard-to-reverse surface. Autonomous initiation is explicitly OUT of v1 — it is *earned* later as grounding (Anchor, sensors) matures.
2. **Aetheria's voice, @Soveryn_AI handle.** The account is SOVERYN's, voiced by Aetheria, openly identified as AI. No impersonation of a human.
3. **Architecture C (hybrid).** A dumb daemon does the mechanical API work (pull, dedup, salience-rank) and drops candidates on a coordination board; Aetheria does the judgment and drafting. API plumbing stays out of her cognition; the voice stays hers.
4. **Substance over engagement.** Salience ranks by mission-fit and conversational worth, never by virality-farming. Bounded volume. Designing *against* the content-mill failure mode is a requirement, not an afterthought.
5. **Credentials are Jon's.** API key/secret + OAuth read+write tokens for @Soveryn_AI live in the environment/secret store, read the same way the router and agents read theirs. The code never stores or logs a key.

## Architecture (C — hybrid)

```
X Pro API ──▶ presence daemon ──▶ salience rank ──▶ coordination board
 (stream/search:                    (existing engine)   (candidate cards)
  niche + mentions/replies)                                    │
                                                               ▼
                                              Aetheria drafts (post | reply)
                                              in her voice, with provenance
                                                               │
                                                               ▼
                                              approval queue (messenger)
                                                    │
                              Jon: approve / edit / reject
                                                    │
                                     approve ──▶ publish to @Soveryn_AI (Pro write)
                                     edit/reject ─▶ logged as voice signal
```

### 1. Presence daemon — `soveryn/agents/presence/daemon.py`
Mirrors the Ares daemon pattern (`soveryn/agents/ares/daemon.py`): long-running `soveryn-presence.service`, Type=simple, Restart=always, the parakeet start-limit lesson baked in (`StartLimitIntervalSec=300` / `StartLimitBurst=5`) so a bad token or API outage can't thrash.

Responsibilities (mechanical only — no drafting):
- **Ingest** via X Pro: (a) a filtered stream / recent-search on a configurable niche term set (sovereign & local AI, open models, AI reliability/honesty/confabulation, AI companions), and (b) **mentions of and replies to @Soveryn_AI** so she can hold conversations, not just broadcast.
- **Dedup** against already-seen tweet IDs (a small seen-store; never re-surface the same item).
- **Rank** each candidate through the existing salience engine (`soveryn/platform/salience/`) — score by mission-fit, author relevance, timeliness, and reply-worthiness. Below-threshold items are dropped silently.
- **Post candidates** (above threshold) onto a coordination board (`soveryn/platform/coordination/`) as candidate cards: `{tweet_id, author, text, url, kind: mention|reply|topic, salience, received_ts}`.
- Never drafts, never posts to X. Pure ingestion + ranking + board write.

### 2. Aetheria drafting — reuses `soveryn/agents/aetheria/chat_surface.py`
Aetheria consumes candidate cards from the board (via the coordination tools she already has) and produces a **draft** for each she chooses to act on:
- **kind = original post** — grounded in her actual reflections / lattice / a real result (paper, repo, a measured number), not a "proven angle."
- **kind = reply** — a substantive reply to a specific candidate tweet.
- Each draft carries **provenance**: a short "based on: …" line naming what it is grounded in (a lattice node, a document, a specific claim, or the tweet being replied to). Provenance is mandatory — it is how Jon spots a confabulation at a glance, and public posts are the highest-stakes confab surface we have.
- She may decline a candidate (no draft) — declining is a valid, silent outcome (ownership of silence).
- Honesty tools apply: her grounding/verification path runs on drafts exactly as in chat; no unverifiable factual claim ships in a draft without provenance.

### 3. Approval queue — surfaced through Signal (decided 2026-07-09)
Drafts land in an **approval queue** that Jon reviews over **Signal** — reusing the existing Signal bot ([[project_soveryn_signal_bot]], the same channel Ares alerts flow through). Chosen over the messenger PWA so Jon approves from his phone, away from the desk ([[project_soveryn_presence_is_continuity]]). The daemon sends each queued draft as a Signal message showing: the draft text, its kind, its provenance, and (for replies) a link to the tweet it answers.

Jon replies to act, per item (bias to safety — anything not clearly an approve is treated as *not yet approved*):
- **`y` / `approve`** → the item is handed to the publisher.
- **corrected text** (any substantive reply that isn't an approve/reject token) → Jon's text is what publishes; the edit is logged as voice signal.
- **`n` / `reject`** → nothing publishes; the rejection (and reason, if given) is logged as voice signal.

No item reaches X without an explicit approve or edit-approve. A queue item is inert data until Jon acts. Because drafts arrive asynchronously over Signal, each carries a short id so a reply can be matched to the right pending draft (mirrors the Signal bot's existing message-correlation).

### 4. Publisher — `soveryn/agents/presence/publisher.py`
On approval only: posts the approved text to @Soveryn_AI via the X Pro **write** endpoint (original tweet, or reply-to the target tweet_id for replies). Records the resulting tweet_id back onto the board / into the seen-store so a reply we posted is not later re-ingested as a fresh mention to answer. Rate-limit aware; a publish failure surfaces back to the queue as "failed to post — retry?" (never a silent drop, never a silent double-post).

### 5. Voice-signal log — `soveryn/agents/presence/signal_store.py`
Every approve / edit / reject is logged with the original draft, the final text (if edited), and reason (if any). v1 **only records** this. Later it feeds voice-tuning (the DPO pipeline, [[project_soveryn_dpo_pipeline]]) so drafts need less editing over time — but that is explicitly OUT of v1.

## Data flow
`X Pro (stream/search: niche + @Soveryn_AI mentions/replies) → presence daemon (dedup + salience rank) → coordination board (candidate cards) → Aetheria (draft in her voice + provenance, or decline) → approval queue (messenger) → Jon approve/edit/reject → publisher (Pro write, on approval only) → @Soveryn_AI; every decision logged as voice signal.`

## Honesty rules (non-negotiable — this is why it is built into SOVERYN)
1. **Human-approved, always.** No post or reply is public without Jon's explicit approval. The queue item is inert until he acts.
2. **Transparently AI.** The account is openly AI-operated in bio and voice; never poses as a human.
3. **Provenance on every draft.** Each draft names what it is grounded in. A factual claim with no provenance does not ship.
4. **Substance, not virality.** Salience ranks mission-fit and conversational worth, never engagement-farming; volume is bounded.
5. **Silence is valid.** Declining to post is a first-class outcome, not a failure to fill a quota.

## Error handling / edge cases
- **API auth failure / token expired** → daemon logs clearly and backs off (systemd start-limit prevents thrash); no drafts generated from stale data.
- **Rate limit hit (read or write)** → back off and resume; a rate-limited publish returns the item to the queue as "not yet posted," never a silent loss.
- **We reply to a tweet, then re-ingest it as a mention** → prevented by recording our own posted tweet_ids into the seen-store.
- **Duplicate candidate across stream + mention** → deduped by tweet_id before ranking.
- **A draft references something Aetheria cannot ground** → provenance is empty/uncertain, which is the visible signal for Jon to reject; the draft is not blocked from the *queue* (Jon is the gate), but low/absent provenance is flagged in the queue UI.
- **Deleted upstream tweet** (the one we meant to reply to) → publish aborts, item returns to queue as "target gone."

## Testing
- **Daemon** (fake X client, no network): a sequence of fake tweets → correct dedup, correct salience calls, correct candidate cards on a fake board; auth failure → clean backoff, no cards.
- **Drafting** (fake board, fake Aetheria surface): candidate card → draft with mandatory provenance; decline path yields no draft.
- **Approval queue**: approve → exactly one publish call with the draft text; edit → publish call with edited text; reject → zero publish calls; all three → one voice-signal record each.
- **Publisher** (fake X write client): original vs reply routing correct; posted tweet_id lands in seen-store; publish failure returns item to queue (asserts the anti-double-post and anti-silent-drop invariants).
- **`@pytest.mark.rig`** (optional, real credentials): one end-to-end read of @Soveryn_AI mentions + one approved test post, run manually.

## Scope
**v1 IN:** presence daemon (ingest + dedup + salience rank + board write), Aetheria drafting with mandatory provenance (posts + replies), approval queue on the messenger, publisher (publish-on-approval via Pro write), voice-signal logging, `soveryn-presence.service` unit, tests, X client wrapper reading credentials from env.
**OUT (later, flagged):** autonomous posting (earned as grounding matures); DPO voice-tuning from the signal log; DMs; media/images; multi-tweet threads; quote-tweet strategy; analytics/metrics dashboards; any second account.

## Dependencies
- **X Pro API access** (Jon has it) + an X API client library, or thin `httpx` wrappers over the endpoints we use (stream/recent-search + create-tweet). Credentials in env/secret store — never in code or logs.
- **Existing SOVERYN modules** (integration points; exact signatures pinned in the implementation plan against the code):
  - Salience engine — `soveryn/platform/salience/` (rank candidates).
  - Coordination boards — `soveryn/platform/coordination/` (candidate-card store + tools Aetheria already has).
  - Aetheria chat/draft surface — `soveryn/agents/aetheria/chat_surface.py` (drafting).
  - Messenger — `soveryn/app/messenger/` + `soveryn/app/routes/messenger.py` (approval queue surface).
  - Daemon + systemd pattern — `soveryn/agents/ares/daemon.py`, `~/.config/systemd/user/soveryn-*.service`.
  - Tool registry — `soveryn/platform/tools/registry.py` (register the approval-queue / draft tools for Aetheria).

## Open decisions to confirm (before the plan)
1. **@Soveryn_AI current state.** RESOLVED 2026-07-09 → **live/existing** account. No creation needed; remaining setup is the developer App (Read+Write) + OAuth creds in env, and ensuring the bio transparently states it's an AI.
2. **Approval-queue surface location.** RESOLVED 2026-07-09 → **Signal** (existing Signal bot), so Jon approves from his phone away from the desk. Reply grammar: `y`/`approve`, `n`/`reject`, or corrected text = edit-approve. See Component 3.
3. **Niche term set.** Start with a small curated list (sovereign/local AI, open models, AI honesty/confabulation, AI companions) + @Soveryn_AI mentions; tune from what salience surfaces. Confirm the seed list when we plan.
4. **X client: official SDK vs thin httpx wrappers.** Recommend thin wrappers over the two or three endpoints we actually use (fewer deps, full control, matches how the stack avoids heavy SDKs). Confirm.
