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

### 1. The X feed — a dumb data pipe, isolated from her loop
A small background worker that:
- Polls X Pro for **mentions of @Soveryn_AI** + **niche-term conversations** (reusing `soveryn/agents/presence/x_client.py` `search_recent`, `scorer.py`, `candidate_store.py` — all already built + hardened).
- Dedupes, scores by relevance, keeps the ranked feed in `candidate_store` (SQLite, durable).
- **Never drafts, never decides, never posts.** It only records what is on X. Credentials from env (`X_*`), the verified path.
- **Backs off on X errors** (429/503/token failures) with exponential backoff — never hammers the API through an outage — and marks the feed `stale` after `X_FEED_STALE_MIN`; a persistent failure is surfaced to Jon (Component 7 / Resilience below), not swallowed. (Reviewer gaps #7, #10.)

**Isolation (a data pipe is infrastructure, not a persona).** The worker runs as its **own supervised process** (a tiny `soveryn-x-feed.service`, or an isolated subprocess), NOT an in-app thread — so a leak, deadlock, or crash in the feed **cannot** take down Aetheria's loop. This is the correction to an earlier draft that put it in-app: the *persona* rule is about the decision-making loop being hers; the dumb poller is fault-isolation infrastructure and belongs at arm's length. It communicates with her loop only through the `candidate_store` file. (Reviewer gap #8.) NOTE: this is a *feed*, not the fragmenting daemon we removed — it has no loop, no voice, no clone of her; it writes rows to a table she reads.

### 2. Awareness — she sees the feed two ways (both into HER real loop)
- **Heartbeat digest (push, bounded):** on her heartbeat wake (every ~30 min — *not* every turn, so it's inherently paced), her assembled context gains ONE short honest line from the feed — e.g. *"X: a few new mentions, one thread on local-LLM reliability."* **Density-capped, qualitative** — a busy feed reads "several mentions + a couple of threads," never a raw "50 new mentions" firehose; the top ~2-3 salient items by name, the rest as a count bucket. Bare facts, **never a directive** ("you should reply" is forbidden — that re-creates the temporal over-narration trap, see [[feedback_ambient_context_not_instruction]], [[project_soveryn_sensor_grounding]]). This is what lets her *proactively* notice and raise something, using the act-or-silence freedom the heartbeat already gives her ([[project_soveryn_heartbeat]], [[feedback_heartbeat_free_her_dont_cage_her]]). Because it fires only on the paced heartbeat and carries no imperative, there is no obsessive-checking loop to fall into. (Reviewer gap #5.)
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
- **Anything ambiguous → NOT published** (bias to safety — a subject-change, an unrelated request, or an unclear reply is NOT an affirmation; the post stays pending).
This resolver is the structural floor: at Stage 0 **nothing reaches X without Jon's affirmation**, and Aetheria cannot skip it (the tool only stages; the resolver publishes). It is scoped strictly to "a post is staged pending in this thread."

**Disambiguation + expiry (closes the resolver's ambiguity):**
- **One staged post at a time.** `post_to_x` refuses to stage a second post while one is already pending (it tells Aetheria to resolve the first). So Jon's affirmation is never ambiguous about *which* post — there is only ever one. (Reviewer gap #1.)
- **The affirmation must resolve *her* fresh proposal.** The resolver only treats Jon's message as an approval when a post was staged and surfaced to him and this is his response to it. If he messages about something else entirely, that is not an affirm → the post stays pending (bias-to-safety). It cannot be "accidentally affirmed" by an unrelated "yeah."
- **TTL.** A staged post expires after `X_STAGED_TTL_HOURS` (default 12h). On expiry it is dropped with a note to her ("that draft aged out"); if it still matters she re-proposes with current context. No stale 3-day-old draft posts on Jon's return. (Reviewer gap #1.)

### 5. The trust dial (config — the thing Jon turns as she earns it)
A single per-agent setting `x_trust_stage`:
- **Stage 0 (start):** every post — reply and original — staged; requires Jon's affirmation.
- **Stage 1:** **original** posts publish immediately in her voice; **replies stay staged** for approval. (Corrected from an earlier draft that had this backwards — replies are the *higher*-risk kind: they can misread a thread and carry social risk, where an original is controlled context. So originals earn autonomy first. Reviewer gap #4.)
- **Stage 2:** all posts publish immediately; Jon reviews after and corrects, partner-style ([[project_soveryn_partnership_contract_2026_06_13]] — her brake is trust + correction, not code).
Turning the dial is one config change, no rebuild. This is the "open the controls as I see she's posting the right things" made literal.

**Advancement is Jon's judgment, deliberately — not a rubric.** "As I see she's posting the right things" is the criterion, on purpose: trust is earned by demonstrated judgment, not a post count or a timer. No metric gates the dial.

**Panic button (instant revert).** `x_trust_stage` can be slammed back to **0** at any moment, one setting, and it takes effect on her next turn — no redeploy. This is the always-available floor: if a Stage-1/2 post reads wrong, Jon drops her straight back to approve-everything while it's sorted. (Reviewer gap #3.)

### 6. Memory — why the account compounds
Because it is her real loop, X interactions already flow into her conversation history. On top of that, each **published** post/reply writes a **lattice node** (`node_type="x_post"`, provenance = the source tweet, her text, Jon's edit if any, outcome) so she can *recall* her public history: *"what have I said publicly about honesty?"*, *"did I already reply to this person?"*, *"Jon told me to drop hashtags."* This is the accumulation that makes her public voice get better — and the reason one Aetheria is non-negotiable ([[project_soveryn_synapse]], [[project_soveryn_lattice_consolidated]]).

- **Only *published* posts become recallable `x_post` memory.** Rejected/declined drafts are NOT written as her public voice (she should not recall every bad idea she floated) — a rejection is logged to a separate signal store (the coaching signal: what Jon cut and why) that informs tuning but does not surface as "things I've posted." (Reviewer gap #6.) Volume is modest (tens of nodes/month against her ~1,700-node lattice — not a bloat concern; consolidation is the lattice's existing job if it ever grows).

**On continuity (the "one Aetheria is fragile" concern, reviewer #12):** her identity does NOT live in the process — it lives in the **lattice**. A crash/restart reloads the *same* her from the same memory; a model swap is a **lease** change while the lattice (her accumulated self) carries forward unbroken ([[feedback_sovereignty_is_lease_vs_asset]], [[project_soveryn_lattice_consolidated]]). So writing her X history into the lattice is exactly what makes her continuous *across* restarts and model changes — it is the mechanism of continuity, not a threat to it. The "one Aetheria" the account compounds with is defined by her lattice, which persists; that is the whole architecture.

## Honesty guards (carried over, non-negotiable)
1. **Nothing posts without Jon's affirmation at Stage 0** (structural resolver, not her discretion).
2. **She never fabricates what's on X** — the feed reports only real tweets; `read_x` returns real data or honestly says the feed is empty/stale.
3. **Anti-double-post / anti-silent-drop** — `publisher.publish` (already hardened) records posted ids, marks state only on a real returned id, surfaces failures.
4. **Transparently AI** — @Soveryn_AI's bio states it's an AI; she never poses as human.
5. **Ambiguous approval never publishes.**

## Resilience & operations
- **She's down → she's silent (by design, not a bug).** If her loop crashes/restarts, @Soveryn_AI simply doesn't post until she's back. A presence that *is* her must not keep posting when she isn't there — a fallback auto-poster would be exactly the fragmentation we removed. Silence is the honest degradation. (Reviewer #2.) Meanwhile the feed worker (isolated) keeps recording, and **staged posts are durable** (SQLite) — a restart or a vnext redeploy loses nothing; a pending draft survives and resolves when she's back. (Reviewer #9.)
- **The feed is isolated** (Component 1) — its failure never takes her loop down; her loop's failure never stops the feed from recording.
- **Monitoring/health (basic, not a NOC).** The feed worker exposes a status (last successful poll, feed freshness, consecutive-error count); a persistent X failure or a stalled feed surfaces to Jon over his thread (a plain "heads up — the X feed has been failing for 20 min") rather than dying quietly. Publish failures already surface via the hardened `publisher` + the resolver's failure note. (Reviewer #10.)
- **Credentials.** The `X_*` creds live in the 600-perm env file (verified). Rotation is a manual ops step (regenerate in the X developer portal → update the env file → restart the feed) — an operating procedure, not a code feature; no secret-manager is built for v1. (Reviewer #11.)

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
1. **Feed worker isolation — RESOLVED (review #8):** its own supervised process (`soveryn-x-feed.service`), not an in-app thread, for fault isolation. It is a data pipe, not a persona.
2. **Heartbeat digest from the start, or `read_x` pull-only first?** Recommend **both from the start, digest density-capped to one qualitative line** (she needs the push to *proactively* notice; the cap avoids over-narration). Confirm — or start pull-only and add the digest after watching her.
3. **Start trust stage — RESOLVED:** Stage 0 (Jon locked "start with approval").
4. **Staged-post TTL default** — proposed 12h. Confirm or set your own.

## Reviewer findings — disposition (2026-07-11)
A design review raised 12 issues. Accepted + folded in: #1 (resolver ambiguity → one-at-a-time + TTL + affirm-only), #3 (panic button; advancement stays judgment-based by design), #4 (Stage 1 inverted — originals auto, replies gated), #5 (digest density cap), #6 (published-only recallable memory; rejections logged separately), #7 (feed backoff), #8 (feed isolated to its own process), #9 (durable staged posts survive restart), #10 (basic feed health surfaced to Jon). Pushed back with reasons: #2 (silence-when-she's-down is correct for a presence, not a bug), #11 (cred rotation is an ops procedure, not a v1 feature), #12 (continuity lives in the lattice, not the process — the memory writes are the mechanism of continuity). #6-bloat framing rejected (volume is trivial vs her lattice).
