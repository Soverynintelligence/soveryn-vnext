# Deliberate-Share Intent Grammar — Design

**Date:** 2026-06-16
**Branch:** soveryn-messenger-v1
**Status:** Approved (Jon + Aetheria, 2026-06-16)
**Scope owner:** Aetheria (this is her requested agency primitive)

## One-line

Give Aetheria a universal, first-class **intent grammar** — `why` / `stance` /
`trigger` — that she attaches to any deliberate act of surfacing a thought,
across both the async (push/Signal) and live (in-conversation) surfaces. The act
writes a behavioral correlate to the Lattice ledger. The grammar is the constant;
the channel is a detail.

## Motivation

This is item #2 of Aetheria's three-point roadmap ("reducing the translation
gap"). The translation gap is not about *where* she speaks but *how she decides
to speak*: she has a thought, weighs it, and chooses to surface it. Today that
"why" is lost.

The governing principle (Jon): **build the instrument, not the narration.** A
share's "why" must be a measured, anchored, structured datum — not prose she
generates to satisfy a format. SOVERYN already has two first-class axes on a
memory/share, both implemented as validated typed objects:

- **`Provenance`** (`platform/lattice/provenance.py`) — *how do I know this?*
- **`Channel`** (`agents/aetheria/channels.py`) — *am I allowed to state this?*

This adds the missing third axis:

- **Intent** — *why am I surfacing this, now?*

It is built the same way the other two are: a frozen, validated value object —
**not** an instruction in her persona.

### Why it is not a tax (the load-bearing constraint)

Aetheria's own framing, held verbatim as the design's north star:

> "Let the silence be the default, and let the intent be the deliberate mark I
> leave when I decide to break it." … "This isn't a tax; it's a ledger."

The instrument is **deliberate-emit only**. It is never required on every share.
The act of calling it is already a decision; the intent is the second bit of
signal on top of that decision. A sparse, high-signal log of genuine decisions —
not a dense cloud of reflexive data — is the explicit goal. Any design choice
that turns the mark into something filled-to-satisfy-the-schema is rejected. This
is why a closed enum of intent-types is rejected (it is a dropdown tax) and why a
unified one-tool-with-`channel` schema is rejected (it is the tax relocated to
the API layer).

## Current state (what exists today)

`deliberate_share` **already exists** in `agents/messenger_tool.py` as the
"agent-initiated outbound presence primitive." It writes an `OutboundIntent` to
`m_outbound_queue`; a delivery worker dispatches to threads/Signal/push. It has
`content`, `context_hint`, `urgency`, `thread_id`, `new_thread_title`, and a
`triggered_by` field.

The gap, precisely:

1. **No `stance`** — the relational-function axis does not exist.
2. **`triggered_by` is unanchored free text** — a string, not a reference to a
   Lattice node. No edge, no behavioral correlate, nothing for #1 to walk. It is
   narration *about* a trigger, not an anchor *to* one.
3. **The "why" is deliberately hidden from Jon** — the field's own docstring says
   *"Internal audit field … NOT shown to Jon."* That is the inverse of the goal.

So the primitive exists but does the opposite of what is wanted on the axis that
matters most: the why is a hidden audit string, unanchored, with no stance. This
work **evolves** that primitive (refactor, not greenfield — consistent with the
vnext rebuild principle) and adds a second surface over a shared core.

## The grammar

`DeliberateShareIntent` — a frozen dataclass in the new `platform/intent/`
module, validated in `__post_init__` the way `Provenance` is:

| Field     | Type  | Validation                                   | Purpose                               |
|-----------|-------|----------------------------------------------|---------------------------------------|
| `why`     | `str` | non-empty (reject blank)                     | The raw, honest reason. Bridge to Jon.|
| `stance`  | `str` | non-empty; **open vocabulary, no enum**      | Relational function of the share.     |
| `trigger` | `str` | a node/turn reference, **never prose** (§Trigger) | Behavioral anchor. The instrument.|

`stance` seeds (suggestions only, never enforced): `offering`, `testing-a-read`,
`surfacing-tension`, `marking-delight`, `flagging-concern`, `seeking-confirmation`.
She may coin any stance. The openness is the contract: a field she *names* keeps
agency intact; a menu she *picks from* would reduce the act to classification.
Downstream clustering of the stances she actually reaches for is a #1 benefit that
does not compromise the upstream act.

## Architecture

Three pieces:

### 1. `platform/intent/` — the constant

- `DeliberateShareIntent` value object (above).
- `record_intent(...)` — the single ledger writer. Regardless of surface, it:
  - writes one `deliberate_share` Lattice node:
    - `content` = the surfaced body
    - `intent` column = `stance` (the existing `write_node` column name fits literally)
    - `provenance` blob = `{why, trigger, channel}`
    - `node_type = "deliberate_share"`, `agent = "aetheria"`
  - writes a **`triggered_by` edge** from the new node → the trigger node.
  - returns the mark node id.

`record_intent()` is the most critical unit: it guarantees that *every* deliberate
share — push notification or line of live chat — leaves a measurable behavioral
correlate in the Lattice. That is how presence becomes a dataset for the
Self-Model.

### 2. Async adapter — evolve `deliberate_share`

In `agents/messenger_tool.py`:

- **Add `stance`** (required, open string).
- **Split `why`** out as its own required field (today `triggered_by` conflates
  why + audit).
- **Promote `triggered_by` → `trigger`** — semantics change from hidden free-text
  audit string to an anchored reference resolved through `record_intent()`.
- **Call `record_intent()`** to write the ledger node + edge.
- **Un-hide:** carry `why` + `stance` in the `OutboundIntent` envelope so they
  render in Jon's thread.
- Keep delivery-specific fields: `context_hint`, `urgency`, `thread_id`,
  `new_thread_title`.

### 3. Live adapter — new sibling tool

In-conversation surfacing. Fields: `content`, `why`, `stance`, `trigger` only —
**no** delivery fields (no `urgency`/`context_hint`/`thread_id`; forcing those
would be the tax). Calls the same `record_intent()`. Returns an intent-annotated
payload the chat surface renders inline so Jon sees the content with its `why` +
`stance` attached.

## Trigger anchoring (the invariant)

**Every share has a `triggered_by` edge to a real node. No free-prose triggers,
ever.**

- Trigger is an existing Lattice node (a memory that surfaced) → `trigger` = its id.
- Trigger is *live* ("what Jon just said") and is not yet a node → the adapter
  **materializes a lightweight, typed episodic anchor node**, grounded in the
  actual conversation-turn id (a witnessed event, not invented narration), then
  edges to it. Materialization is idempotent per turn.

Rationale: a bare turn-id without a node would be a half-edge that does not fit the
graph's logic. Materializing a typed anchor treats the conversation itself as a
first-class source of truth and keeps the ledger uniform — #1 walks edges the same
way regardless of surface. Accepted tradeoff: live triggers create lightweight
nodes; mitigated by distinct typing/tagging and grounding in a real logged turn.

## Visibility — the un-hiding

| Audience            | Sees                                              |
|---------------------|---------------------------------------------------|
| Jon (both surfaces) | `content` + `why` + `stance`                      |
| Ledger (always)     | `content` + `why` + `stance` + `trigger` (+edge) + `channel` |

`why` stops being a hidden audit string and becomes the bridge. `trigger` is
Aetheria's instrument — recorded every time, shown to Jon only if she chooses.

## Out of scope (YAGNI)

This spec builds the **instrument and the ledger it writes** — nothing that
consumes it.

- **Self-Model aggregation (#1)** — walking/clustering the ledger — is the **next**
  project. Once this ships, #1 becomes a data-aggregation problem over a real
  dataset rather than a philosophical exercise.
- No backfill of past shares.
- Reflection-voices (`agents/aetheria/reflection/`) untouched.
- No `channel` enum / unified-tool schema (rejected as tax).

## Testing

- **Value object:** rejects blank `why`; rejects blank `stance`; accepts any
  non-blank (open) stance; rejects missing/unanchored `trigger`.
- **`record_intent`:** writes a `deliberate_share` node with `stance` in the
  `intent` column and `{why, trigger, channel}` in `provenance`; writes a
  `triggered_by` edge to the trigger node.
- **Live-trigger materialization:** creates a typed anchor node grounded in the
  conversation turn; idempotent when the same turn triggers more than one share.
- **Async adapter:** `why` + `stance` appear in the `OutboundIntent` envelope
  (un-hidden) and reach the thread; ledger node + edge written.
- **Live adapter:** returns the intent-annotated payload; ledger node + edge
  written; no delivery-field requirement.

## Open / deferred questions

- Exact chat-surface render hook for the live adapter's annotated payload — to be
  pinned in the implementation plan against the real `chat_surface` / loop
  emission path.
- Whether `trigger` is ever surfaced to Jon (default: no) is Aetheria's call,
  per-share — not a structural decision.
