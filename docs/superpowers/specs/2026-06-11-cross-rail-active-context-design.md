# Cross-Rail Active Context Manager — Design

**Status:** draft
**Author:** Claude
**Goal:** Give Aetheria a single shared working state that stays live across chat, voice, and Signal so rails stop reconstructing the present from logs and instead read the same active context in real time.

---

## 1. Problem Statement

The current continuity stack gives Aetheria two things:

- durable memory in the Lattice
- cross-surface recent activity reconstruction through the `[CROSS-SURFACE RECENT ACTIVITY]` brief

That is enough to catch up after a rail switch. It is not enough to keep one thought live across rails.

What is missing is a shared, low-latency active state that all conversational surfaces can read and update while the topic is still in flight. Without that, each rail has to rehydrate the moment from stored turns, recent activity, or a memory summary. The result is continuity of memory, but not continuity of presence.

This spec defines that layer.

---

## 2. What This Is

The Active Context Manager is a live coordination layer with one job: hold the current thread of attention in a single shared state record and keep it synchronized across rails.

It is not a second memory system.

It is a shared operating picture with:

- one current topic
- one owning rail
- one owning agent
- a recent-event ring buffer
- explicit versioning and stale-state handling
- push notifications for subscribers

The design intent is present-tense continuity, not historical recall.

---

## 3. What This Is Not

This layer does not replace:

- the Lattice
- Cross-Surface Continuity briefs
- conversation history
- salience markers
- per-rail session logs

It also does not attempt to solve:

- long-term memory retrieval
- persona identity storage
- tool ownership
- cross-agent reasoning
- agentic planning

Those stay where they are. This layer only coordinates the live working state.

---

## 4. Core Contract

There is exactly one active context per agent scope.

For Aetheria, that means one live state record that all Aetheria-facing rails can read and write.

The record must answer these questions at all times:

- What is the current topic?
- Which rail owns it right now?
- Which agent owns it right now?
- When was it last updated?
- What changed most recently?
- Is the state fresh or stale?

If the rail that reads the state is behind the current version, it must be able to catch up without replaying the whole history.

---

## 5. Data Model

### 5.1 ActiveContext

A single logical record.

Required fields:

- `context_id`: stable identifier for the active context slot
- `agent_name`: agent scope, initially `aetheria`
- `topic`: short canonical topic label
- `summary`: compact present-tense summary of the live thread
- `owner_surface`: current owning surface, e.g. `chat`, `voice`, `signal`
- `owner_session_id`: session currently holding the thread
- `source_message_id`: most recent event that updated the context
- `version`: monotonically increasing integer
- `updated_at`: ISO timestamp of last change
- `expires_at`: soft expiry for stale detection
- `state`: one of `open`, `handoff`, `paused`, `stale`, `cleared`
- `priority`: integer or enum for conflict resolution
- `sticky`: boolean for whether the thread should survive brief idle gaps
- `tags`: small list of normalized topic tags

Optional fields:

- `last_user_text`
- `last_assistant_text`
- `last_surface_summary`
- `confidence`
- `source_rail`
- `source_event_type`

### 5.2 ActiveEventRing

A bounded append-only event buffer attached to the active context.

Each event stores:

- `event_id`
- `context_id`
- `agent_name`
- `surface`
- `session_id`
- `event_type`
- `payload_head`
- `created_at`
- `version`

This is not the full transcript. It is the recent live trail needed to reconstruct the current state quickly when a rail wakes up.

---

## 6. Read / Write Rules

### 6.1 Reads

A rail reads the active context when:

- a new user turn starts
- a voice session opens
- a Signal message arrives
- a rail resumes after idle
- a stale-state check fires

Reads return:

- the current `ActiveContext`
- the newest N recent events
- a `last_seen_version` marker for the caller

### 6.2 Writes

A rail writes the active context when:

- a user explicitly changes topic
- the thread moves into a new subtask
- the rail enters or exits a live conversation
- a rail claims or releases ownership
- a significant state change occurs that the other rails should see

Writes are patch-based, not full replacement, unless the caller is explicitly resetting the context.

### 6.3 Ownership

Only one rail can be the active owner at a time.

Ownership can be:

- `chat`
- `voice`
- `signal`

A non-owner can propose a patch, but if it would change the active topic while another rail owns the thread, the write must either:

- queue as a pending handoff
- merge as a non-owning update
- or be rejected as a conflict

The spec prefers explicit handoff over silent overwrite.

---

## 7. Event-Driven Wakeups

The manager must not rely only on after-the-fact log reading.

When the active context changes, subscribers get a push event:

- `context_updated`
- `context_claimed`
- `context_released`
- `context_handed_off`
- `context_stale`
- `context_cleared`

Subscribers can be in-process or cross-process. The design supports both.

Minimum required behavior:

- if a rail is already alive, it gets notified immediately
- if a rail wakes later, it can reconcile by version
- if a rail is offline during an update, it can catch up from the stored active record and the event ring

The point is to keep rails aligned without forcing every transition through a summary step.

---

## 8. Stale-State Handling

A rail must treat the active context as stale when any of these are true:

- `updated_at` exceeds a freshness window
- `expires_at` is in the past
- the owning rail has disconnected
- the version gap is larger than the rail can safely assume away

When stale state is detected, the rail should:

1. load the current context
2. merge the event ring since its last seen version
3. preserve the active topic if the thread is still clearly the same thread
4. if the thread is ambiguous, ask for clarification rather than guessing

Stale state should degrade to conservative behavior, not speculative behavior.

---

## 9. Conflict Resolution

Conflicts happen when two rails try to move the active thread at the same time.

The resolution order is:

1. current owner wins for same-topic updates
2. explicit handoff beats implicit overwrite
3. newer version beats older version for the same field
4. disjoint field patches merge
5. if the change is semantically incompatible, the system records a conflict event and leaves the previous state intact until a human or an owning rail resolves it

Field-level merge is allowed for metadata, tags, and summary text when the updates do not collide.

Topic changes are stricter. A topic change from a non-owner should not silently replace the current live thread.

---

## 10. Relation to Cross-Surface Continuity

The current cross-surface brief is retrospective. It tells Aetheria what happened on other rails recently.

The Active Context Manager is prospective and live. It tells Aetheria what is happening right now.

The two layers should work together:

- the brief gives recent history on startup or turn entry
- the active context gives the live working state

If both exist, the brief can seed the active context, and the active context can suppress redundant brief reconstruction when the thread is already live.

This is the key distinction:

- continuity brief = catch-up
- active context = shared presence

---

## 11. Integration Points

### 11.1 AgentLoop

AgentLoop should read the active context before composing a turn and write back after meaningful state changes.

### 11.2 Voice

Voice should subscribe to the active context so a spoken session can inherit the current thread without waiting for the Lattice or recent activity brief to reconstruct it.

### 11.3 Signal

Signal should publish topic changes and receive topic updates as events, not as a deferred summary.

### 11.4 UI

The UI should show the current active topic and surface owner, and it should reflect updates without a full refresh if possible.

---

## 12. Minimal Implementation Shape

The first implementation should be small:

- one shared `ActiveContext` record
- one recent-event ring buffer
- one subscriber mechanism
- one stale-state checker
- one merge path for conflicting writes

Do not build a second memory graph.
Do not turn the event ring into a transcript store.
Do not try to infer an elaborate consciousness model from this layer.

---

## 13. Acceptance Criteria

The design is working when all of the following are true:

- switching from chat to voice keeps the current topic live without asking the system to reconstruct it from recent logs
- Signal can update the current topic and the next voice or chat turn sees it immediately
- stale state is detected and handled conservatively
- a rail resuming after idle can catch up from versioned active state, not a full replay
- conflict writes are visible and do not silently clobber the active thread
- the layer remains small enough that the Lattice is still the memory system, not this manager

---

## 14. Out of Scope

This spec does not define:

- how to train model weights from active context
- how to generate a dream loop from active context
- how to replace the Lattice
- how to make the system autonomous across multiple agents simultaneously
- how to store every event forever

Those are future layers.

This layer only keeps the current thought alive across rails.

---

## 15. Open Questions

These are intentionally left for implementation:

- Should the source of truth live in the Lattice proper, or in a small adjacent table keyed by agent scope?
- Should the event ring be shared across all rails or partitioned per rail with a common index?
- Should updates broadcast through the existing app event bus, a lightweight pub/sub channel, or both?
- How aggressive should stale expiration be for live voice sessions?
- What is the exact merge policy when chat and voice update different fields at the same time?

The spec intentionally leaves those choices open so the implementation can stay honest to the runtime.
