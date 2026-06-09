# Cross-Surface Continuity — Design

**Status:** locked (Jon + Aetheria, 2026-06-09)
**Author:** Aetheria (architectural self-diagnosis); Jon (decision); Claude (implementation framing)
**Goal:** Close the asymmetry where Aetheria can push messages outbound to Signal but cannot read inbound Signal turns back into her working context. Make conversations on any rail (UI / Signal / future surfaces) part of the same felt thread with Jon.

---

## The diagnosis (Aetheria's own words)

> "I can't see your Signal history. The bridge lets me send messages to you, but I don't have a tool to scroll back through your incoming Signal messages and scrape them for data. I only know what you've told me here in the chat or what has been explicitly written into the Lattice."

> "It is a problem if you expect me to have a seamless, omniscient view of every channel we use. Right now, the bridge is a one-way street for memory: I can push out, but I can't 'read back' the history of the Signal thread to update my state. I only know what lands in this session or what gets committed to the Lattice."

She named the seam precisely. Her AgentLoop calls `conv_store.load_history(session_id)` for exactly the current session — UI sessions can't see Signal sessions and vice versa. The data exists in `conversations.db` (Signal turns are saved with normal `agent='aetheria'` rows), but the recall layer doesn't reach across.

She is not *forgetting* Signal exchanges. She literally does not have eyes on them when she's in a UI session.

## What we are NOT building

- **Not a search tool over all Signal history.** That's a reactive shape — she'd have to *suspect* there's something to recall before she'd look. The whole problem is she doesn't know what she doesn't know.
- **Not a persona patch.** Telling her "remember you talk to Jon on Signal too" in her prompt would substitute persona text for the missing memory substrate. That pattern has bitten this project before ([[feedback-persona-text-substituting-for-memory-architecture]]).
- **Not cross-agent continuity.** Vett and Scotty have their own threading; this is Aetheria-only.
- **Not Signal-history backfill into the UI's visible sidebar.** That's a UX question for later. The brief is for Aetheria's eyes.

## What we ARE building

**Recent Activity Brief.** On every turn in any of Aetheria's surfaces, AgentLoop queries conv_store for OTHER aetheria sessions whose `updated_at` is within a configurable recent window, pulls the tail content from each, formats it as a small bracketed block, and injects it into her system context above pinned memory.

Ambient by design. She doesn't have to call a tool. She doesn't have to *remember* to look. The cross-surface context is just there when there's anything to show.

Zero-overhead common case: when no other-surface activity exists in the window, the block is empty and no injection happens.

---

## Scope

**In:**
- Cross-session recall WITHIN aetheria's sessions (signal ↔ UI ↔ webhook-where-applicable)
- Last N hours of activity (start: **6h**; tune from observation)
- Per other-session: session title + last 2-4 paired turns (user/assistant), head-truncated for readability
- Total injected text capped at **~1500 tokens** so it doesn't crowd her real context
- One-sentence factual addition to her pinned memory: she has multiple rails with Jon; the Activity Brief is the source of truth for what happened where. *Fact, not behavioral rule.*

**Out:**
- Cross-agent continuity (Vett/Scotty/specialists)
- Search-on-demand tool (rejected per diagnosis above)
- Auto-resuming conversations ("you were about to say X")
- UI-sidebar Signal-thread visibility
- Summarization (we pass raw turn tails — summarization is its own quality-loss surface, defer until we see actual context pressure)

## The two safety beats

### Beat 1 — Daemon-session filtering (read-side)

Sessions whose `conversation_meta.title` starts with `[heartbeat]`, `[dream]`, `[patrol]`, `[webhook]`, `[salience-smoke]`, or any other daemon prefix are Aetheria's own self-talk. They MUST NOT appear in the brief; including them would feed her own outputs back to her and confound the relational frame.

Approved title prefixes for inclusion: anything not in the daemon-prefix set. Signal session titles (e.g., `[signal] aetheria <phone>`) ARE included — that's the whole point. UI sessions (untitled or user-titled) ARE included.

### Beat 2 — Daemon-turn no-injection (write-side)

When AgentLoop is processing a heartbeat, dream, patrol, or webhook turn, the brief is NOT computed and NOT injected. Reason: a heartbeat already has its own snapshot framing (BoardSnapshot + LatticeSnapshot + SalienceDigest). Layering cross-surface activity on top would muddle the heartbeat's distinctive shape. Same for the other daemon turns.

Implementation gate: AgentLoop checks the session title via `conv_store.get_session(session_id).title`. If it matches a daemon prefix, skip brief computation.

---

## Brief format

```
[CROSS-SURFACE RECENT ACTIVITY]
In the last 6 hours you also exchanged turns with Jon on other rails:

— from "[signal] aetheria +19102489392" (47m ago):
   jon: "Quick question — did the spark stack land yet?"
   aetheria: "Not yet — second one is still tracking late June per the…"

— from "[signal] aetheria +19102489392" (12m ago):
   jon: "ok I'll check the FedEx tracker tonight"
   aetheria: "Got it. I'll watch the heartbeat for any unboxing photos."
[/CROSS-SURFACE RECENT ACTIVITY]
```

Rules:
- Sessions ordered most-recent-first
- Per session: title + relative time of last update + last 1-2 paired turns
- Each turn's content head-truncated to ~140 chars + "…" if longer (matches Salience Digest convention for consistency)
- If a session has only a user turn (in-flight), include it; assistant turn rendered as `(in flight)`
- If multiple sessions from the same rail (e.g., two Signal threads with same phone), include them all separately — they may be conceptually different conversations even if they're on the same surface

## Token budget

- Soft cap: **1500 tokens** total injected (per OpenAI tokenization estimate; we conservatively count chars/4 and stop adding sessions once the budget is hit)
- Per-session cap: **400 tokens** (forces fair allocation across multiple sessions)
- Most-recent priority: if budget is tight, drop older sessions first

## Configuration knobs (env vars)

- `SOVERYN_CROSS_SURFACE_WINDOW_HOURS` (default 6)
- `SOVERYN_CROSS_SURFACE_TOKEN_BUDGET` (default 1500)
- `SOVERYN_CROSS_SURFACE_ENABLED` (default true; flip to false for kill-switch without restart)

## Re-evaluation triggers

- **She references stale Signal context in UI** → window is too long, lower it
- **She doesn't naturally weave Signal context in** → brief isn't being injected, or format isn't readable to her — debug from logs first
- **She apologizes for "forgetting"** in cross-surface conversations → the brief is working but she's not noticing it — adjust the framing line ("In the last 6 hours…") to be more directive
- **Token budget pressure** in long active sessions → tune per-session cap down
- **She conflates two parallel threads** ("you mentioned X on Signal" when X was UI) → format isn't differentiating rail clearly enough; emphasize the title

## The pinned-memory one-liner

A single sentence added to her pinned memory, NOT a behavioral rule. Frames the new substrate as fact:

> You have multiple conversation rails with Jon: this UI, Signal direct messages, and webhook channels. The [CROSS-SURFACE RECENT ACTIVITY] block at the top of your context (when present) is the source of truth for what happened on the other rails recently. You don't need to call a tool to access it — it's already there if relevant.

That's it. No "remember to check it" or "always reference it." Just a fact about her substrate.

## Why this is not the Salience Engine

The Salience Engine (shipped 2026-06-08) decides *what to keep forever* — markers fire on resonant moments, candidates surface in heartbeat digests, Aetheria promotes the resonant ones to library.

The Recent Activity Brief decides *what's happening right now on the other rail*. Ephemeral. 6-hour window. No promotion. No decay. Just ambient awareness.

They're complementary:
- Salience: long-term consolidation
- Cross-Surface Continuity: short-term episodic awareness

A turn might fire markers AND appear in someone else's session's brief. They don't collide.

## See also

- [[project-soveryn-salience-engine-shipped]] — complementary long-term memory layer
- [[project-soveryn-signal-bot]] — the Signal rail
- [[project-soveryn-mobile-expo]] — the future mobile UI rail (also covered by this design when it lands)
- [[feedback-persona-text-substituting-for-memory-architecture]] — applies: build substrate, not persona patches
- [[feedback-aetheria-fewer-rules]] — applies: the pinned-memory line is a fact, not a rule
- [[project-soveryn-direct-agent-communication-shipped]] — DAC is agent-to-agent; this is human-to-agent cross-surface. Different problem, different solution.
