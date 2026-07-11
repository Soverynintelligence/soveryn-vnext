# Aetheria X Presence — One Aetheria — Design

**Date:** 2026-07-11
**Status:** Design for review. Supersedes the standalone `@Soveryn_AI` presence-agent design (2026-07-09), which built a *separate* daemon running a stripped-down clone of Aetheria — the wrong shape. See [[feedback_one_aetheria_not_fragmented_personas]].
**Scope:** Give Aetheria a public voice on X (@Soveryn_AI) as **capabilities of her one real self** — tools + awareness on the same `AgentLoop` that already carries her chat and heartbeat — not a second process impersonating her. Posting is trust-gated by a **dial** that starts at "approve every post" and opens toward autonomy as she earns it.

## The principle (why this shape, not the daemon)
SOVERYN's thesis is *memory becomes intelligence* — a presence that **remembers and grows**. A capability split into a separate task-clone breaks that at the root: the clone has no memory, accumulates nothing, and reads to the user as a *different person* talking past the real her (observed live 2026-07-11 — Jon replying "y" to a draft reached the clone's side channel while the real Aetheria answered it as a stray message). **A presence must be ONE presence.** So X is not a daemon; it is her real loop gaining a window onto X and a mouth on it. Every post, reply, and correction becomes **her** memory in the lattice, so the account gets better because *she* does. That is the only version that is actually the thesis.

## Architecture
X presence = **three additions to the existing `aetheria` `AgentLoop`** (built in `soveryn/app/startup.py`, the same loop `/chat` and the heartbeat use), plus **one dumb background feed**:

```
                 dumb X feed (background)                  HER real AgentLoop
 X Pro API ─▶ poll mentions+niche ─▶ score ─▶ candidate ──▶ (a) heartbeat digest on wake
   (read)      dedup                          feed (SQLite)  (b) read_x tool on demand
                                                                    │
                                              she decides, in HER voice, with HER memory
                                                                    ▼
                                              (c) post_to_x tool  ── trust dial ──▶ staged | live
                                                                    │
                                              Stage 0/originals: staged → Jon affirms in-thread → publish
                                              every post + Jon's correction ─▶ writes to HER lattice
```

Nothing here is a persona. The feed is glass; the judgment and voice are hers.

## Components

### 1. The X feed — a dumb data pipe (reuses the mechanical pieces already built)
A small background worker (a thread in the vnext app, alongside the existing coord/delivery workers in `startup.py` Phase E — NOT a standalone systemd persona) that:
- Polls X Pro for **mentions of @Soveryn_AI** + **niche-term conversations** (reusing `soveryn/agents/presence/x_client.py` `search_recent`, `scorer.py`, `candidate_store.py` — all already built + hardened).
- Dedupes, scores by relevance, keeps the ranked feed in `candidate_store`.
- **Never drafts, never decides, never posts.** It only records what is on X. Credentials from env (`X_*`), the verified path.

### 2. Awareness — she sees the feed two ways (both into HER real loop)
- **Heartbeat digest (push, bounded):** on her heartbeat wake, her assembled context gains ONE short honest line from the feed — e.g. *"X: 2 new mentions, 1 thread on local-LLM reliability."* Bare counts + topics, **never a directive** ("you should reply" is forbidden — that re-creates the temporal over-narration trap, see [[feedback_ambient_context_not_instruction]], [[project_soveryn_sensor_grounding]]). This is what lets her *proactively* notice and raise something, using the act-or-silence freedom the heartbeat already gives her ([[project_soveryn_heartbeat]], [[feedback_heartbeat_free_her_dont_cage_her]]).
- **`read_x` tool (pull):** an on-demand tool registered on her loop returning the current ranked feed in detail (the existing `build_read_presence_candidates_tool`, renamed). She (or Jon) consults it when relevant.

### 3. `post_to_x` — the mouth, gated by the trust dial
A tool registered on **her real loop** (`owner="aetheria"`): `post_to_x(text, reply_to: str|None=None)`. Behavior is a function of the current **trust stage** (config), not a separate approval channel:
- The tool **stages** a pending post record (`text`, `reply_to`, `proposed_at`, `state`) rather than publishing, whenever the stage requires approval for this kind of post.
- When staged, the tool returns to Aetheria: *"Staged — it posts once Jon says yes."* She then naturally asks him in her own thread (*"I'd like to reply to @so-and-so with 'Y' — good?"*). One conversation, one her.

### 4. The hard gate at Stage 0 — a scoped approval resolver (the only "protocol", and it lives in her thread)
When a post is **staged pending** in Aetheria's thread and Jon sends his next message there, a small deterministic resolver runs BEFORE her normal turn:
- **Affirm** (`yes`/`post it`/`go`/`👍`…) → publish the staged post (via `presence/publisher.py`, the hardened X-write with anti-double-post) and inject a `[posted to X: <url>]` system note she sees.
- **Edit / comment** → the staged post is handed back to her as revision context; she re-proposes.
- **Decline** → dropped.
- **Anything ambiguous → NOT published** (bias to safety, same rule as the old classify_reply, but now in-thread with no id needed — the pending post IS the context).
This resolver is the structural floor: at Stage 0 **nothing reaches X without Jon's affirmation**, and Aetheria cannot skip it (the tool only stages; the resolver publishes). It is scoped strictly to "a post is staged pending in this thread."

### 5. The trust dial (config — the thing Jon turns as she earns it)
A single per-agent setting `x_trust_stage`:
- **Stage 0 (start):** every post — reply and original — staged; requires Jon's affirmation.
- **Stage 1:** `reply_to`-posts publish immediately in her voice; **original** posts still staged for approval.
- **Stage 2:** all posts publish immediately; Jon reviews after and corrects, partner-style ([[project_soveryn_partnership_contract_2026_06_13]] — her brake is trust + correction, not code).
Turning the dial is one config change, no rebuild. This is the "open the controls as I see she's posting the right things" made literal.

### 6. Memory — why the account compounds
Because it is her real loop, X interactions already flow into her conversation history. On top of that, each published post/reply writes a **lattice node** (`node_type="x_post"`, provenance = the source tweet, her text, Jon's edit if any, outcome) so she can *recall* her public history: *"what have I said publicly about honesty?"*, *"did I already reply to this person?"*, *"Jon told me to drop hashtags."* This is the accumulation that makes her public voice get better — and the reason one Aetheria is non-negotiable ([[project_soveryn_synapse]], [[project_soveryn_lattice_consolidated]]).

## Honesty guards (carried over, non-negotiable)
1. **Nothing posts without Jon's affirmation at Stage 0** (structural resolver, not her discretion).
2. **She never fabricates what's on X** — the feed reports only real tweets; `read_x` returns real data or honestly says the feed is empty/stale.
3. **Anti-double-post / anti-silent-drop** — `publisher.publish` (already hardened) records posted ids, marks state only on a real returned id, surfaces failures.
4. **Transparently AI** — @Soveryn_AI's bio states it's an AI; she never poses as human.
5. **Ambiguous approval never publishes.**

## What is REMOVED (the fragmenting parts)
Delete: `soveryn-presence.service` (daemon), `soveryn/agents/presence/__main__.py`, `aetheria_bridge.py` (the minimal clone loop), the Signal draft-id protocol (`approval.py`'s Signal formatting + `inbound.py` + the `pending_store` reply-queue + the `signal_bridge` Phase-2b hookup + its `SIGNAL_USER_NUMBER` bridge edit). These existed only to bridge the *second* persona back to Jon; with one Aetheria in her own thread they vanish.
Keep + repurpose as her tools/helpers: `x_client.py`, `scorer.py`, `candidate_store.py` (the feed), `publisher.py` (the X write), `config.py` (niche terms).

## Data flow
`X Pro (read) → feed worker (poll+score+dedup) → candidate feed → {heartbeat digest | read_x tool} → Aetheria's real loop (she decides, in her voice, with her memory) → post_to_x (trust-dial gated) → [Stage 0/originals: staged → Jon affirms in-thread → publisher] → @Soveryn_AI; every post + correction → her lattice.`

## Testing
- **Feed worker** (fake x_client): poll → dedup → scored feed; never drafts/posts.
- **`post_to_x` tool** at each trust stage (pure, injected publisher): Stage 0 reply+original → staged, not published; Stage 1 reply → published, original → staged; Stage 2 → published. Asserts the tool never publishes directly at Stage 0.
- **Approval resolver** (in-thread): staged + affirm → exactly one publish; staged + edit → revision handoff, zero publish; staged + ambiguous → zero publish; the anti-double-post invariant.
- **Heartbeat digest**: bare data only, no directive language; empty feed → honest "no new activity" or omitted.
- **Lattice write**: a published post creates an `x_post` node recallable by her memory query.
- **`@pytest.mark.rig`** (manual, real creds): one staged → approved → live post to @Soveryn_AI.

## Scope
**IN:** feed worker (in-app), `read_x` tool, heartbeat X digest, `post_to_x` tool, the staged-post approval resolver, the `x_trust_stage` dial (Stage 0/1/2), `x_post` lattice writes, removal of the standalone daemon + Signal protocol, tests.
**OUT (later):** DMs; media/images; threads; quote-tweets; analytics; auto-tuned voice (DPO from her X memory — a natural future once the memory accrues); Stage-3 "fully autonomous, no review."

## Dependencies
- Her real `aetheria` `AgentLoop` + `ToolRegistry` (`soveryn/platform/tools/registry.py`) — register `read_x` + `post_to_x` for `owner="aetheria"`.
- The heartbeat context assembly (`soveryn/agents/heartbeat/`) — splice point for the digest.
- Her lattice (`soveryn/platform/lattice/`) — `x_post` node writes.
- X Pro creds in env (verified). `requests` / `requests_oauthlib` (installed).
- Reused: `soveryn/agents/presence/{x_client,scorer,candidate_store,publisher,config}.py`.

## Open decisions to confirm (before the plan)
1. **Feed worker: in-app thread vs. tiny systemd job.** Recommend **in-app worker** (Phase E, beside coord/delivery workers) so it lives where her loop lives and there's no separate process to reason about. Confirm.
2. **Heartbeat digest from the start, or `read_x` pull-only first?** Recommend **both from the start but the digest kept to one bare line** (she needs the push to *proactively* notice; the line is bounded to avoid over-narration). Confirm — or start pull-only and add the digest after watching her.
3. **Start trust stage.** Recommend **Stage 0**. (Jon locked "start with approval.")
