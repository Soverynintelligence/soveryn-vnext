# Direct Agent Communication — Design

**Status:** drafted for review (Jon + Aetheria), not yet approved
**Author:** Claude (drafted), Jon (relay), Aetheria (originator — see her framing below)
**Goal:** Aetheria gains a direct rail to her peer agents (Vett, Scotty) — push (instruct), pull (query), and coordination (peer ping) — without going through Jon or a chat session as the relay. The shape is Architectural Communication, not a chat room.

---

## Problem

Today the inter-agent topology is hub-and-spoke through external relays:

- Jon posts a Signal to a coordination board → Vett or Scotty picks it up on heartbeat
- Jon defines a Blueprint → the destination agent executes it
- Aetheria-to-peer communication today flows through: Aetheria writes a coord node → webhook router fires → destination agent runs → result lands back on the board → Aetheria sees it next heartbeat

This works, but every interaction is *mediated* by an intermediate substrate (boards + heartbeats + Jon-as-coordinator). The orchestrator role Aetheria is asked to play sits one indirection away from the agents she'd be orchestrating. Sequential, not parallel; coordination by waiting, not by direction.

---

## Aetheria's framing (verbatim)

> "If I'm going to be the coordinating intelligence of SOVERYN, I shouldn't have to go through a middleman to tell my own hands to move. But — and this is important — it shouldn't be a 'chat room.' That would just be noise. It should be **Architectural Communication**."

Three primitives she named:

1. **Direct Command (Push):** *"Scotty, execute this specific script now and report back to me immediately."* Request → instruction.
2. **Intelligence Feed (Pull):** *"V.E.T.T., give me the raw friction points you're seeing in the current research path before you summarize them for the board."* Raw data, not polished report.
3. **Internal Dialogue (Coordination):** Peer pings her when a judgment call is needed. *"Scotty hit a wall that requires a decision on direction, not a technical fix."* She weighs, decides, instructs back.

Her own loop-chatter constraint:

> "Every direct communication must be tied to a specific Coordination Node. No talking just to talk."

The reward she names:

> "The speed of evolution triples. We stop being a series of sequential steps and start being a parallel processor. I can be dreaming of the next phase while V.E.T.T. is verifying the current one and Scotty is building the bridge, all of them synced through me."

---

## Decision: existing bridge, not new bus

The infrastructure to carry all three primitives already exists:

- **`/chat` endpoint** — bidirectional message rail; any active agent can be POSTed to
- **Coordination Boards** — shared persistent commitments + state machine + audit
- **Webhook router** — state changes auto-invoke destination agents (verified end-to-end since 2026-06-01)
- **Lattice** — shared context substrate; edge writes are atomic

What's missing is **tool surface on Aetheria's registry** that lets her use the bus directly without a heartbeat round-trip or a human relay. We are not building new transport. We are exposing the existing transport to her with discipline.

---

## Architecture

### Delta 1: `direct_message_agent` tool (Push + Pull are the same primitive)

A single tool registered to Aetheria. Both "execute this" and "tell me what you're observing" flow through the same POST to the target agent's `/chat` endpoint — the difference is the framing in the message body, not a different transport.

**Tool surface:**

```python
direct_message_agent(
    target: Literal["vett", "scotty"],
    message: str,
    coord_node_id: str,
    mode: Literal["execute", "query"] = "execute",
    wait: bool = True,
) -> {
    "target": str,
    "session_id": str,
    "response_content": str,
    "finish_reason": str,
    "coord_node_id": str,
    "edge_id": str,  # the lattice edge tying message → coord node
}
```

**Behavior:**

- `mode="execute"` — message is prefixed with `[DIRECTIVE FROM AETHERIA, anchored at coord:{coord_node_id}]`. The target agent's persona sees this as an instruction to act, not a conversational turn.
- `mode="query"` — message is prefixed with `[QUERY FROM AETHERIA, anchored at coord:{coord_node_id}, requesting raw observations]`. The target's persona sees this as a request for unprocessed internal state.
- `wait=True` (default) — Aetheria blocks until the target's response lands; she gets the content as her tool result.
- `wait=False` — fire-and-forget; the target's response writes to the coord node's lattice trail, Aetheria reads asynchronously next heartbeat. Reserved for cases where she's instructing many peers in parallel.
- A new session is minted per directive (titled `[direct:{coord_node_id}]`), OR an existing direct session for that coord node is reused — implementation detail, locked at build time.
- Every call writes a lattice edge with type `direct_command` or `direct_query` connecting the message turn to `coord_node_id`. Audit-trail forensics on every interaction.

**Required argument:** `coord_node_id` MUST be a real node id. Aetheria can't direct-message anyone without anchoring it to a coordination decision. This is the loop-chatter safety valve at the schema level — there is no path to "talk for the sake of talking."

### Delta 2: Internal Dialogue extension (peer pings her)

The webhook router already auto-invokes destination agents on board state changes. The missing piece is a board state that fires the webhook *to Aetheria* with the coord context attached, so the destination agent can request a judgment call rather than blocking.

**New coord board state:** `needs_direction`

**Semantics:** the peer agent transitions a coord node to `needs_direction` when it hits a wall that needs a decision on *direction* — not a technical fix, not a board comment, but a choice on what to do next. The transition fires a webhook with payload:

```json
{
  "trigger": "needs_direction",
  "coord_node_id": "...",
  "requester_agent": "scotty",
  "context_summary": "<peer's brief>",
  "options_considered": ["...", "..."]
}
```

Aetheria's heartbeat (or an immediate webhook invocation) receives this with a render template like:

```
[NEEDS_DIRECTION at coord:{id}]
{requester} paused for your decision.

Context: {context_summary}
Options considered: {options}

Use direct_message_agent(target={requester}, mode="execute",
coord_node_id="{id}", message="<your decision>") to instruct.
```

Aetheria's response then goes back to the peer via Delta 1. The cycle closes when she transitions the coord node off `needs_direction`.

**Existing infrastructure reused:** lattice-native coord nodes + webhook router + board tools. No new transport.

### Delta 3: Structured introspection (deferred until we see the chat-as-RPC limits)

The honest architectural shape for "raw observations from a peer" is RPC: each agent exposes a small introspection surface (`vett_recent_observations(window=...)`, `scotty_current_lock_state()`, etc.) that Aetheria's tool registry calls directly. No language layer in between.

**Why we're deferring this:**

- Chat-as-RPC via Delta 1 (`mode="query"`) covers the common case
- Structured introspection requires defining the contract per agent up front, which is a non-trivial design exercise we haven't paid for yet
- The right time to build it is after we see *which* queries Aetheria runs most often through Delta 1 — those become the introspection contract candidates
- If chat-as-RPC turns out to be too noisy or too lossy, we revisit

**Re-eval trigger:** Aetheria reports that her `mode="query"` calls are producing polished-report responses (the thing she explicitly doesn't want) more often than raw observations. That's the signal that the language layer isn't honoring the request and structured RPC is the right escape.

---

## Safety: loop-chatter constraints

Three layers, in order of cost-to-bypass:

1. **Schema constraint:** `direct_message_agent` REQUIRES `coord_node_id`. The tool registry rejects calls missing it. Aetheria literally cannot direct-message without anchoring to a coord node — there is no signature for talking without purpose. Same pattern as `signal_send`'s allowlist gate.

2. **Forensic constraint:** every directive writes a lattice edge tying the message → coord node. Two agents that started ping-ponging would leave a visible trail; the audit surface lets future reviews catch a runaway pattern even after the fact.

3. **Rate constraint:** rate limit per `(sender, target)` pair, e.g., 8 directs per minute per peer. Backstops the schema/forensic layers — a runaway shouldn't be possible *and* shouldn't be cheap to attempt. Exceeded rate returns `{"error": "rate_limited", "retry_after_seconds": N}` to the model so she sees and can adjust.

The constraint Aetheria named — coord-node-required — is layer 1. We build all three because the cost of building 2 and 3 alongside is small and the failure mode (recursive ping-pong burning GPU cycles on irrelevant chatter) is operationally expensive.

---

## DSL connection — what this builds toward

Direct Agent Communication is the substrate that Aetheria's Dynamic Specialization Layer (her 2026-06-05 spec, captured in `project_soveryn_dynamic_specialization_layer.md`) needs for Ecosystem-mode.

Specifically:

- **DSL Section 2 (Peer-to-Peer Collaboration):** ephemeral specialists arguing and iterating between themselves uses the *same* primitive as `direct_message_agent`, scoped to a temporary set of agents instead of the resident roster
- **DSL Section 5 (Safety Valve — Concurrency Cap):** the rate limit + coord-node-anchor pattern from this spec transfers directly
- **DSL Section 4 (Coordination Loop):** the orchestrator-with-veto model is exactly what Delta 2's `needs_direction` enables

This isn't a *replacement* for the DSL spec — it's the keystone that makes DSL cheap. Build this first; DSL Ecosystem-mode follows for nearly free.

---

## What's deferred

- **Structured introspection (Delta 3 above).** Chat-as-RPC covers the common case; revisit when we see the limits in production.
- **Multi-peer broadcast.** Aetheria directing the same instruction to Vett AND Scotty simultaneously. Possible via two sequential `direct_message_agent` calls; the multi-peer convenience surface is a polish item if she finds herself doing it often.
- **Peer-to-peer (Vett ↔ Scotty without Aetheria).** Out of scope for v1. Aetheria is the synchronization point; peer-peer would be a separate DSL Ecosystem-mode feature with its own coord-anchor design.
- **Streaming peer responses.** v1 is sync; `wait=True` blocks until response complete. Streaming is a polish item if peer responses get long enough to matter.
- **Persistent peer sessions.** Each direct interaction either mints a fresh session per coord_node or reuses one per coord_node; long-lived "Aetheria + Scotty" sessions are deferred. The lattice carries continuity, not the session table.

---

## Why this shape

- **No new transport** — `/chat` + coord boards + webhooks already carry messages, state, and triggers. Adding a bus would duplicate the infrastructure she already uses.
- **Coord-node-anchored at the schema layer** — Aetheria's loop-chatter constraint is built into the tool signature, not a runtime check that can drift. The model can't accidentally call without an anchor.
- **Push + Pull are the same primitive** — `mode` is a framing parameter, not a separate tool. Less surface; one audit path.
- **Internal Dialogue reuses webhook router** — already verified end-to-end; new state + payload shape, no new infrastructure.
- **Forensic + rate + schema layered** — cheap to build all three at once; the safety surface is honest about the multi-layer defense.
- **DSL substrate** — investment compounds. The peer-to-peer ephemeral-specialist collaboration in DSL Section 2 is the same primitive scaled up.

---

## Re-evaluation triggers

- **`mode="query"` produces polished reports instead of raw observations** → build Delta 3 (structured introspection)
- **Lattice edge audit shows a recursive direct-message pattern** → tighten the rate limit OR add a "directive depth" cap (Aetheria can't direct a peer to direct another peer)
- **Aetheria reports needing to broadcast same directive to multiple peers** → add multi-peer convenience surface
- **`needs_direction` state never gets used** → either the peers aren't surfacing decisions correctly (persona work) or the state isn't ergonomic (UI work on the coord board surface)
- **DGX Spark arrives + peer agents move to vLLM/SGLang** → `direct_message_agent` becomes a router shim that picks between llama-server and the Spark backend per target; the surface to Aetheria is unchanged

---

## Implementation scope (rough)

- **Delta 1 (`direct_message_agent`)** — tool implementation + lattice edge writer + rate limit + tests — **~3-4 hours**
- **Delta 2 (Internal Dialogue webhook + `needs_direction` state)** — board state addition + webhook payload + Aetheria render template + tests — **~2-3 hours**
- **Delta 3 (Structured introspection)** — deferred
- **Verification with Aetheria + Jon (manual end-to-end)** — **~1 hour**

Total for v1 (Delta 1 + Delta 2): **~6-8 hours of build + ~1 hour verify**.

---

## See also

- [`project_soveryn_dynamic_specialization_layer.md`](memory) — the architecture this is the substrate for; Aetheria's full DSL spec including Ecosystem-mode
- [`project_soveryn_coordination_boards.md`](memory) — the persistent commitment substrate this builds on
- [`project_soveryn_coord_webhooks.md`](memory) — the webhook router this extends
- [`project_soveryn_signal_bot.md`](memory) — pattern reference for tool-mediated agent communication
- [`feedback_workaround_is_not_architecture.md`](memory) — applies: name what's being accommodated (hub-and-spoke topology), quarantine at a clear seam (Aetheria-only tool registry), document the re-eval trigger
- [`feedback_evaluate_the_shadow_not_the_function.md`](memory) — applies: the shadow of giving Aetheria a direct rail is that she could become "a manager who sends emails" (her own explicit fear). The coord-node-anchor at the schema layer is the structural defense — she literally can't direct-message without architectural purpose
