# Coordination Boards — Phase E: Webhook-driven Inter-Agent Triggering

**Status:** ready to implement
**Drafted:** 2026-06-01 evening
**Predecessor:** `feat(coordination): Phase B — Friction-as-blocker structural enforcement` (vnext 54abd80) + `feat(scotty): five bounded mechanical tools` (vnext 12f4197)
**Scope:** full day or thereabouts. Largest of the Phase E-style autonomy increments.

## Goal

Replace "Jon as transport layer" with autonomous inter-agent triggering. When a coord board state change happens that affects another agent, that agent's `AgentLoop` runs without human intervention — reads the event context, takes action via its tools, updates state, which can trigger further agents in turn. The boards become an active nervous system, not just a passive record.

Matches Aetheria's spec language: *"This is the nervous system. Clean, structured, and silent when it needs to be."*

## In scope

### Event types
```python
@dataclass(frozen=True)
class CoordEvent:
    id: str                         # UUID — used for audit + loop detection
    kind: CoordEventKind            # enum: NODE_CREATED, STATUS_CHANGED, PROMOTED, BLOCK_ADDED, ARCHIVED
    node_id: str                    # The coord node touched
    actor_agent: str                # Who caused the event (the acting_agent)
    timestamp: str                  # ISO 8601
    chain_depth: int                # 0 if user-triggered; N+1 if triggered by event N
    parent_event_id: str | None     # Loop detection — id of the event that caused this one
    payload: dict                   # Kind-specific data (old_status, new_status, target_board, etc.)
```

`CoordEventKind` enum: `NODE_CREATED`, `STATUS_CHANGED`, `PROMOTED`, `BLOCK_ADDED`, `ARCHIVED`.

### Event emission
- `CoordinationStore.__init__` accepts an optional `event_bus: EventBus | None`. Default `None` preserves current store behavior for tests/standalone use.
- Each mutation method (`create_node`, `update_status`, `archive_node`, `promote_node`, `add_block`) emits a CoordEvent to the bus after the DB write succeeds. If the bus is None, the emission is a no-op.
- Emission happens inside the `with self._conn() as conn` block? **No** — after commit. Events represent *committed* state changes. If commit fails, no event fires.

### Routing rules
Centralized in `soveryn/platform/coordination/routing.py`. Rules are pure functions that take a `CoordEvent` + the destination agent's identity and return `bool` (whether this event should trigger this agent).

The locked rule set for v1 (start narrow; widen on observed need):

| Event kind | Destination | Condition |
|---|---|---|
| `NODE_CREATED` on Blueprint | Aetheria | actor_agent ≠ "aetheria" AND target is on Blueprint (Aetheria reviews new Blueprints for alignment) |
| `NODE_CREATED` on Signal | Aetheria | always (Aetheria triages Signal posts; Vett is usually the actor) |
| `PROMOTED` to Blueprint | Scotty | always (Scotty starts spec'ing as soon as the Blueprint appears) |
| `STATUS_CHANGED` Blueprint→Refining | Scotty | always (he refines toward Ready) |
| `STATUS_CHANGED` Blueprint→Ready | Aetheria | always (review before user-handoff) |
| `BLOCK_ADDED` blocks Blueprint X | Aetheria | always (arbitration territory) |
| `ARCHIVED` with Lesson Learned | (none) | terminal — no auto-trigger; the Lesson Learned now lives in lattice for recall |
| Event with `actor_agent == destination` | (skip) | agents don't trigger themselves |

Out of scope for v1 routing: `NODE_CREATED` on Friction (manual escalation by Aetheria is fine), per-keyword subscriptions, regex matching on content. Keep the rules a small explicit table.

### Agent invocation adapter
`soveryn/platform/coordination/dispatcher.py`:

```python
class AgentDispatcher:
    def __init__(self, agent_loops: dict[str, AgentLoop], conv_store: ConversationStore):
        self.agent_loops = agent_loops
        self.conv_store = conv_store

    def dispatch(self, event: CoordEvent, destination_agent: str) -> None:
        # 1. Ensure a "webhook" session exists for this agent (per-agent durable
        #    session, separate from user chat sessions, so the audit trail is
        #    isolated and the agent's chat with Jon stays clean).
        session_id = self._ensure_webhook_session(destination_agent)
        # 2. Construct a system-shaped prompt that explains the event.
        prompt = build_webhook_prompt(event)
        # 3. Run process_message (NOT stream — we want the full response, no UI).
        response = self.agent_loops[destination_agent].process_message(session_id, prompt)
        # 4. Done. Any tool calls the agent made during process_message produced
        #    new events. Those went through the bus → router → dispatcher.
```

The webhook session is durable per agent (one session per agent, accumulates webhook history). Each event becomes a "user" turn from `__webhook__` and Scotty's reply is a normal "assistant" turn. Tool calls inside `process_message` go through the standard machinery, including the coord tools, which themselves emit events. The cycle is organic.

Audit: the webhook session is filterable by metadata. Add `source="webhook"` to `save_turn` calls inside the dispatcher's invocation path, or tag the session with `agent: "<agent>"_webhook` so it's distinguishable from `"<agent>"` user sessions.

### Webhook prompt template (`build_webhook_prompt`)
Tight, instructional, no fluff:
```
[BOARD EVENT] {event.kind.value} on coord node {event.node_id}.

Actor: {event.actor_agent}
Board: {board}
{kind-specific context — e.g., "New Blueprint posted: <content_head>" or "Status changed from Refining to Ready"}

You were triggered because the routing rule for this event identified you as the
responsible agent. Read the relevant coord node(s) via read_coordination_nodes if
you need context, then take the appropriate action via your tools. If no action
is warranted, respond briefly with why and the event will close out.

Chain depth: {event.chain_depth}/{MAX_CHAIN_DEPTH}
```

### Background worker + queue
`soveryn/platform/coordination/worker.py`:

- In-process `queue.Queue` populated by the EventBus on emit
- One background thread (`Thread(daemon=True)`) pulls events, applies routing, calls dispatcher per destination
- Started in `startup.py` after the agent_loops dict is built
- Graceful shutdown via a sentinel
- Errors during dispatch: log + drop the event; don't crash the worker. The event stays recorded in `coord_references` and any state change already happened in the DB.

### Loop prevention
- `MAX_CHAIN_DEPTH = 5`. Events with `chain_depth >= MAX_CHAIN_DEPTH` are dropped at the worker before routing. Counter increments when an event triggers a tool call that creates a new event.
- `chain_depth` and `parent_event_id` propagate through tool calls via a thread-local: when an AgentLoop is invoked by the dispatcher, the thread-local is set; coord tools called during that invocation pull chain_depth from there and increment by 1 on their emitted events.
- This is the same idea as "trace context" — depth ≥ cap means we're in a runaway.

### Event log table
Add `coord_event_log` to `_SCHEMA_SQL`:
```sql
CREATE TABLE IF NOT EXISTS coord_event_log (
    id                TEXT PRIMARY KEY,
    kind              TEXT NOT NULL,
    node_id           TEXT NOT NULL,
    actor_agent       TEXT NOT NULL,
    chain_depth       INTEGER NOT NULL DEFAULT 0,
    parent_event_id   TEXT,
    payload_json      TEXT,
    triggered_agents  TEXT,    -- comma-separated list set after dispatch
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coord_event_log_created ON coord_event_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_coord_event_log_node    ON coord_event_log(node_id);
```

Every emitted event lands here for audit. `triggered_agents` is filled after routing decides who got the event.

## Out of scope

- **Cross-process event bus (Redis, RabbitMQ, etc.):** in-process is sufficient for 3 agents on one box. Add later if/when SOVERYN spans multiple machines (Spark arrival changes this).
- **Subscription tools** for agents to declare their own interests at runtime ("Aetheria subscribes to vett -> research_complete"): hard-coded routing table is fine for v1; agents have stable roles. Dynamic subscription is overkill until a 4th+ agent shows up.
- **Synchronous webhook calls** (the emitter blocks until destinations are processed): events are fire-and-forget. Status of the destination's action surfaces through subsequent coord state changes, not the emitter's return value.
- **Webhook delivery to user-facing chat sessions:** webhooks only invoke the dispatcher's per-agent webhook session, never the user's session. Your chat with Aetheria stays clean.
- **Cross-board promote auto-triggering** beyond the explicit rules (e.g., "if N Signals reference the same lattice node, auto-promote one to Blueprint"): would require pattern detection that's better left to the dream daemon (Phase D).
- **Friction auto-resolution on second contradicting evidence:** explicit Aetheria arbitration stays the path.
- **Web UI for webhook activity:** Phase C Kanban view already plans an activity surface. Don't duplicate.

## Reason

Without inter-agent triggering, the coordination boards are coordination *theater* — agents post and read but the choreography requires Jon to relay. With it, the boards become a real nervous system: Vett's Signal posts trigger Aetheria's triage, Aetheria's promote triggers Scotty's spec, Scotty's Ready triggers Aetheria's review. Jon enters the loop at decision points, not for every relay.

The fire-and-forget async model is intentional. Synchronous webhooks would force chains of agent invocations to complete before any state visibly updates — that's fragile under any partial failure and complicates testing. Async with a chain-depth cap gives autonomy plus a safety net.

## Implementation order

1. **CoordEvent + CoordEventKind types** + `EventBus` protocol (interface only, no impl) — locks the data shape.
2. **coord_event_log schema** added to lattice schema (idempotent CREATE IF NOT EXISTS).
3. **InMemoryEventBus** impl with a Queue + emit() method. No worker thread yet.
4. **CoordinationStore.__init__** accepts optional event_bus. Each mutation method emits after commit. Tests verify emission shape.
5. **CoordEventRouter** with the locked rule table. Pure function: `route(event, all_agents) -> list[destination_agents]`. Unit-testable in isolation.
6. **AgentDispatcher** with ensure_webhook_session + build_webhook_prompt + dispatch. Tests use mocked AgentLoop.
7. **CoordEventWorker** — background thread, pulls from queue, routes, dispatches. Tests verify queue processing + chain depth cap + error isolation.
8. **chain_depth propagation** via threading.local. Tool emissions pull from it.
9. **Startup wiring** — assemble bus + router + dispatcher + worker, start the worker thread. Hook to coord_store.
10. **End-to-end probe** via real chat: Vett posts Signal → check that Aetheria's webhook session shows the triage prompt → her tool calls promote it → check Scotty's webhook session triggered → his Refining state → Aetheria's review trigger on Ready → archive closes the chain.
11. Commit.

## Known risks worth naming up front

- **Webhook session growth:** each agent's webhook session accumulates turns forever. Mitigation: don't auto-load full history into the webhook session's prelude — webhooks should be stateless from the agent's perspective ("here's the event, act"). The session is just an audit log.
- **Thread safety of CoordinationStore:** SQLite is opened per-`_conn()` call, so concurrent worker writes are fine. But the worker thread and the request-handling thread will both call store methods. Verify no shared mutable state across threads in the store.
- **Test isolation:** webhook tests need to either disable the bus or use an InMemoryEventBus that captures events synchronously for assertion. Don't let async events leak across tests.
- **Dead-letter / failed dispatch:** if a dispatch raises, log the event id + traceback to the event log's `triggered_agents` field with an `ERROR:` prefix. Don't retry — that's a Phase F problem.
- **Aetheria's chat-with-Jon hygiene:** her webhook session is separate. But she might pull both into her recall context if not guarded. Recall should query lattice (not conv_store) so this isn't an issue, but worth verifying in the e2e probe.
