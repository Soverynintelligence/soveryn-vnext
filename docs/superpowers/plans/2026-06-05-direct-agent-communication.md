# Direct Agent Communication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aetheria gains a direct rail to Vett and Scotty via two new tool surfaces. Delta 1 = `direct_message_agent` (Push + Pull). Delta 2 = `NEEDS_DIRECTION` event kind + `request_direction` peer tool + Aetheria-side webhook rendering.

**Architecture:** Build on existing `/chat` endpoint + coord boards + webhook router. No new transport. Loop-chatter constraint enforced at schema layer (coord_node_id required); rate limit + lattice-edge forensics layer behind. Two new modules: `soveryn/agents/direct_communication/` (the push/pull tool + rate limiter) and extensions to `soveryn/platform/coordination/` (new event kind + `request_direction` tool + routing rule + dispatcher render).

**Tech Stack:** Python (stdlib + urllib), Flask test client / urllib for cross-agent dispatch, existing CoordinationStore + ToolRegistry + InMemoryEventBus + AgentDispatcher.

**Spec:** `docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md`

---

## Task 1: Lattice edge helper for direct-communication audit trail

**Files:**
- Modify: `soveryn/platform/lattice/legacy.py` (add helper)
- Test: `tests/test_lattice_legacy.py` (existing flat test file)

**Why first:** the `direct_message_agent` tool writes a lattice edge per call (the forensic safety layer from the spec). Build the helper standalone first so it can be tested in isolation.

- [ ] **Step 1: Write failing test**

```python
def test_record_direct_communication_edge_writes_typed_edge(tmp_path):
    """A direct-communication edge ties a message-turn id to a coord node
    with relation=direct_command or direct_query."""
    from soveryn.platform.lattice.legacy import (
        LatticeStore, record_direct_communication_edge,
    )
    db = tmp_path / "lattice.db"
    store = LatticeStore(db)
    # Create the two nodes the edge will tie together. Use the existing
    # add_node API the test file already exercises.
    coord_node = store.add_node(agent="aetheria", layer="coord", content="task X")
    msg_node = store.add_node(agent="aetheria", layer="direct_message", content="do Y")

    edge_id = record_direct_communication_edge(
        store=store,
        coord_node_id=coord_node.id,
        message_node_id=msg_node.id,
        mode="execute",
    )

    edges = store.find_edges(source_node_id=msg_node.id)
    assert len(edges) == 1
    assert edges[0].id == edge_id
    assert edges[0].target_node_id == coord_node.id
    assert edges[0].relation == "direct_command"


def test_record_direct_communication_edge_query_mode_writes_direct_query():
    """mode='query' → relation='direct_query'."""
    # ... same shape, mode="query", assert relation == "direct_query"


def test_record_direct_communication_edge_rejects_invalid_mode():
    """Only 'execute' and 'query' are accepted."""
    # ... assert raises ValueError for mode="other"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_lattice_legacy.py -v -k "direct_communication_edge"`
Expected: FAIL (helper doesn't exist).

- [ ] **Step 3: Implement helper**

Append to `soveryn/platform/lattice/legacy.py`:

```python
_DIRECT_COMM_RELATIONS = {"execute": "direct_command", "query": "direct_query"}


def record_direct_communication_edge(
    *,
    store: "LatticeStore",
    coord_node_id: str,
    message_node_id: str,
    mode: str,
) -> str:
    """Write a typed edge tying a direct-message turn back to the
    coordination node it's anchored to. The forensic trail required by
    docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md
    — every direct interaction leaves a visible edge so a runaway pattern
    is detectable from the lattice without trawling chat history.

    Returns the new edge id.
    """
    relation = _DIRECT_COMM_RELATIONS.get(mode)
    if relation is None:
        raise ValueError(
            f"mode must be 'execute' or 'query', got {mode!r}"
        )
    return store.add_edge(
        source_node_id=message_node_id,
        target_node_id=coord_node_id,
        relation=relation,
    ).id
```

(Adapt the `add_edge` call to whatever the existing LatticeStore API is — read it first to match shape.)

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_lattice_legacy.py -v -k "direct_communication_edge"`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/lattice/legacy.py tests/test_lattice_legacy.py
git commit -m "lattice: record_direct_communication_edge helper

Forensic-trail edge writer for Delta 1 of the direct agent communication
spec. relation='direct_command' for mode='execute', 'direct_query' for
mode='query'. Helper validates mode at the boundary.
"
```

---

## Task 2: RateLimiter for per-(sender, target) cap

**Files:**
- Create: `soveryn/agents/direct_communication/__init__.py` (empty)
- Create: `soveryn/agents/direct_communication/rate_limit.py`
- Test: `tests/test_direct_communication_rate_limit.py`

- [ ] **Step 1: Write failing tests**

```python
import pytest
from datetime import datetime, timedelta
from soveryn.agents.direct_communication.rate_limit import DirectCommRateLimiter


def test_under_cap_when_no_calls_recorded():
    limiter = DirectCommRateLimiter(per_minute_cap=8)
    now = datetime(2026, 6, 5, 12, 0, 0)
    assert limiter.under_cap(sender="aetheria", target="vett", now=now)


def test_under_cap_until_cap_reached():
    limiter = DirectCommRateLimiter(per_minute_cap=3)
    now = datetime(2026, 6, 5, 12, 0, 0)
    for _ in range(3):
        limiter.record(sender="aetheria", target="vett", now=now)
    assert not limiter.under_cap(sender="aetheria", target="vett", now=now)


def test_independent_caps_per_sender_target_pair():
    """Aetheria → Vett at cap shouldn't block Aetheria → Scotty."""
    limiter = DirectCommRateLimiter(per_minute_cap=2)
    now = datetime(2026, 6, 5, 12, 0, 0)
    for _ in range(2):
        limiter.record(sender="aetheria", target="vett", now=now)
    assert limiter.under_cap(sender="aetheria", target="scotty", now=now)


def test_cap_resets_after_minute_window():
    limiter = DirectCommRateLimiter(per_minute_cap=2)
    t0 = datetime(2026, 6, 5, 12, 0, 0)
    for _ in range(2):
        limiter.record(sender="aetheria", target="vett", now=t0)
    # 61 seconds later, the window has rolled
    t1 = t0 + timedelta(seconds=61)
    assert limiter.under_cap(sender="aetheria", target="vett", now=t1)


def test_retry_after_seconds_when_capped():
    """When over cap, calculate seconds until oldest call falls out of window."""
    limiter = DirectCommRateLimiter(per_minute_cap=1)
    t0 = datetime(2026, 6, 5, 12, 0, 0)
    limiter.record(sender="aetheria", target="vett", now=t0)
    t1 = t0 + timedelta(seconds=15)
    retry_after = limiter.seconds_until_under_cap(
        sender="aetheria", target="vett", now=t1,
    )
    assert retry_after == 45  # 60 - 15
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_direct_communication_rate_limit.py -v`
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Implement**

```python
# soveryn/agents/direct_communication/rate_limit.py
"""Per-(sender, target) rate limit for direct_message_agent.

Backstops the schema-layer coord_node_id constraint AND the forensic
lattice-edge audit trail. If a runaway pattern slips past both upstream
layers, this caps the damage and surfaces a structured retry signal
back to the model.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Lock

_WINDOW_SECONDS = 60


class DirectCommRateLimiter:
    """Sliding-window per-(sender, target) cap. Thread-safe."""

    def __init__(self, *, per_minute_cap: int = 8) -> None:
        self._per_minute_cap = per_minute_cap
        self._calls: dict[tuple[str, str], deque[datetime]] = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key: tuple[str, str], now: datetime) -> None:
        cutoff = now - timedelta(seconds=_WINDOW_SECONDS)
        q = self._calls[key]
        while q and q[0] < cutoff:
            q.popleft()

    def under_cap(self, *, sender: str, target: str, now: datetime) -> bool:
        with self._lock:
            self._prune((sender, target), now)
            return len(self._calls[(sender, target)]) < self._per_minute_cap

    def record(self, *, sender: str, target: str, now: datetime) -> None:
        with self._lock:
            self._prune((sender, target), now)
            self._calls[(sender, target)].append(now)

    def seconds_until_under_cap(
        self, *, sender: str, target: str, now: datetime,
    ) -> int:
        with self._lock:
            self._prune((sender, target), now)
            q = self._calls[(sender, target)]
            if len(q) < self._per_minute_cap:
                return 0
            oldest = q[0]
            seconds = _WINDOW_SECONDS - int((now - oldest).total_seconds())
            return max(seconds, 0)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_direct_communication_rate_limit.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/direct_communication/__init__.py \
        soveryn/agents/direct_communication/rate_limit.py \
        tests/test_direct_communication_rate_limit.py
git commit -m "direct_communication: DirectCommRateLimiter

Sliding-window per-(sender, target) cap, thread-safe, returns
seconds_until_under_cap for the model-facing retry signal. Default
cap of 8/minute per peer. Schema (coord_node_id required) and forensic
(lattice edge per call) layers sit above; this is the third defense."
```

---

## Task 3: `direct_message_agent` tool — Aetheria's push/pull primitive

**Files:**
- Create: `soveryn/agents/direct_communication/tools.py`
- Test: `tests/test_direct_communication_tools.py`

- [ ] **Step 1: Write failing tests (mocking HTTP + lattice edge writer + rate limiter)**

```python
import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from soveryn.agents.direct_communication.tools import (
    build_direct_message_agent_tool,
)
from soveryn.platform.tools.registry import ToolArgError


def _build_tool(rate_limiter=None, http_poster=None, edge_writer=None,
                vnext_base="http://127.0.0.1:5001", owner="aetheria"):
    """Test helper — inject all collaborators."""
    return build_direct_message_agent_tool(
        owner_agent=owner,
        rate_limiter=rate_limiter,
        http_poster=http_poster,
        edge_writer=edge_writer,
        vnext_base=vnext_base,
    )


def test_direct_message_agent_rejects_missing_coord_node_id():
    """Schema-layer loop-chatter defense — no message without an anchor."""
    tool = _build_tool()
    with pytest.raises(ToolArgError, match="coord_node_id"):
        tool.handler({
            "target": "vett",
            "message": "do X",
            # coord_node_id deliberately absent
        })


def test_direct_message_agent_rejects_invalid_target():
    """Only vett or scotty — Aetheria can't direct-message herself."""
    tool = _build_tool()
    with pytest.raises(ToolArgError, match="target"):
        tool.handler({
            "target": "aetheria",
            "message": "x", "coord_node_id": "node-1",
        })


def test_direct_message_agent_execute_mode_prefixes_directive():
    """The wire message Vett sees is prefixed with [DIRECTIVE FROM AETHERIA, ...]."""
    posted = {}
    def fake_poster(url, body, timeout):
        posted["url"] = url
        posted["body"] = body
        return {"content": "ack", "session_id": "sess-1", "finish_reason": "stop"}

    tool = _build_tool(http_poster=fake_poster)
    result = tool.handler({
        "target": "vett",
        "message": "process the new audit findings",
        "coord_node_id": "node-42",
        "mode": "execute",
    })
    assert posted["url"].endswith("/chat")
    assert posted["body"]["agent"] == "vett"
    msg = posted["body"]["message"]
    assert "[DIRECTIVE FROM AETHERIA" in msg
    assert "coord:node-42" in msg
    assert "process the new audit findings" in msg
    assert result["response_content"] == "ack"


def test_direct_message_agent_query_mode_prefixes_query():
    """Query mode uses [QUERY FROM AETHERIA, ...] framing."""
    posted = {}
    def fake_poster(url, body, timeout):
        posted["body"] = body
        return {"content": "raw obs", "session_id": "s", "finish_reason": "stop"}
    tool = _build_tool(http_poster=fake_poster)
    tool.handler({
        "target": "vett",
        "message": "what friction are you seeing right now?",
        "coord_node_id": "node-9",
        "mode": "query",
    })
    msg = posted["body"]["message"]
    assert "[QUERY FROM AETHERIA" in msg
    assert "coord:node-9" in msg
    assert "raw observations" in msg.lower()


def test_direct_message_agent_writes_lattice_edge_on_success():
    """Every successful call records a forensic edge tying message → coord node."""
    edge_calls = []
    def fake_edge(coord_node_id, message_node_id, mode):
        edge_calls.append((coord_node_id, message_node_id, mode))
        return "edge-1"
    def fake_poster(url, body, timeout):
        return {"content": "ack", "session_id": "s", "finish_reason": "stop"}
    tool = _build_tool(edge_writer=fake_edge, http_poster=fake_poster)
    result = tool.handler({
        "target": "vett", "message": "do X",
        "coord_node_id": "node-1", "mode": "execute",
    })
    assert len(edge_calls) == 1
    assert edge_calls[0][0] == "node-1"
    assert edge_calls[0][2] == "execute"
    assert result["edge_id"] == "edge-1"


def test_direct_message_agent_returns_structured_error_when_rate_capped():
    """Rate-limit returns structured {error, retry_after_seconds}, not raise."""
    from soveryn.agents.direct_communication.rate_limit import DirectCommRateLimiter
    limiter = DirectCommRateLimiter(per_minute_cap=0)  # always-capped
    tool = _build_tool(rate_limiter=limiter)
    result = tool.handler({
        "target": "vett", "message": "x",
        "coord_node_id": "node-1", "mode": "execute",
    })
    assert result.get("error") == "rate_limited"
    assert isinstance(result["retry_after_seconds"], int)


def test_direct_message_agent_returns_structured_error_on_chat_failure():
    """Downstream /chat 5xx → {error, message} structured result."""
    def failing_poster(url, body, timeout):
        from urllib.error import HTTPError
        import io
        raise HTTPError(url, 502, "bad gateway", hdrs={}, fp=io.BytesIO(b""))
    tool = _build_tool(http_poster=failing_poster)
    result = tool.handler({
        "target": "vett", "message": "x",
        "coord_node_id": "node-1", "mode": "execute",
    })
    assert result.get("error") == "dispatch_failed"
    assert "502" in result["message"]


def test_direct_message_agent_default_mode_is_execute():
    posted = {}
    def fake_poster(url, body, timeout):
        posted["body"] = body
        return {"content": "ack", "session_id": "s", "finish_reason": "stop"}
    tool = _build_tool(http_poster=fake_poster)
    tool.handler({
        "target": "vett", "message": "x", "coord_node_id": "node-1",
    })  # no mode arg
    assert "[DIRECTIVE FROM AETHERIA" in posted["body"]["message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_direct_communication_tools.py -v -k "direct_message_agent"`
Expected: FAIL (tool doesn't exist).

- [ ] **Step 3: Implement**

```python
# soveryn/agents/direct_communication/tools.py
"""direct_message_agent tool — Aetheria's direct rail to peer agents.

Push (mode=execute) and pull (mode=query) flow through the same primitive:
a POST to the target's /chat endpoint with a framing prefix that the
target's persona reads as either a directive or an information request.

Loop-chatter defenses in layered order:
  1. Schema — coord_node_id is REQUIRED at the tool registry level
  2. Forensic — every successful call writes a lattice edge
  3. Rate — DirectCommRateLimiter caps per-(sender, target) pair

See docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Callable

from soveryn.agents.direct_communication.rate_limit import DirectCommRateLimiter
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


_VALID_TARGETS = frozenset({"vett", "scotty"})
_VALID_MODES = frozenset({"execute", "query"})

_DIRECTIVE_PREFIX = (
    "[DIRECTIVE FROM AETHERIA, anchored at coord:{cid}]\n"
    "Act on this instruction now and report back to me with the result.\n\n"
)
_QUERY_PREFIX = (
    "[QUERY FROM AETHERIA, anchored at coord:{cid}]\n"
    "Give me raw observations — your current internal state on this. "
    "Skip the polished summary; I want the unprocessed read.\n\n"
)


def _default_http_poster(url: str, body: dict, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def build_direct_message_agent_tool(
    *,
    owner_agent: str = "aetheria",
    rate_limiter: DirectCommRateLimiter | None = None,
    http_poster: Callable[[str, dict, float], dict] | None = None,
    edge_writer: Callable[[str, str, str], str] | None = None,
    vnext_base: str = "http://127.0.0.1:5001",
    dispatch_timeout_seconds: float = 240.0,
) -> ToolSpec:
    """Build Aetheria's direct_message_agent tool. Collaborators injected
    so the tool is testable without network or DB."""
    limiter = rate_limiter or DirectCommRateLimiter()
    poster = http_poster or _default_http_poster
    # edge_writer is None in tests that don't care about the audit edge

    def handler(args: Mapping[str, Any]) -> Any:
        target = args.get("target")
        message = args.get("message")
        coord_node_id = args.get("coord_node_id")
        mode = args.get("mode", "execute")
        # wait kwarg exists in the schema but v1 always blocks; deferred.

        if not isinstance(coord_node_id, str) or not coord_node_id.strip():
            raise ToolArgError(
                "coord_node_id is required — every direct communication must be "
                "tied to a Coordination node. See the spec's loop-chatter "
                "constraint."
            )
        if target not in _VALID_TARGETS:
            raise ToolArgError(
                f"target must be one of {sorted(_VALID_TARGETS)}, "
                f"got {target!r}"
            )
        if mode not in _VALID_MODES:
            raise ToolArgError(
                f"mode must be one of {sorted(_VALID_MODES)}, got {mode!r}"
            )
        if not isinstance(message, str) or not message.strip():
            raise ToolArgError("message must be a non-empty string")

        now = datetime.now()
        if not limiter.under_cap(sender=owner_agent, target=target, now=now):
            retry = limiter.seconds_until_under_cap(
                sender=owner_agent, target=target, now=now,
            )
            return {
                "error": "rate_limited",
                "retry_after_seconds": retry,
                "target": target,
                "coord_node_id": coord_node_id,
            }

        prefix = _DIRECTIVE_PREFIX if mode == "execute" else _QUERY_PREFIX
        wire_message = prefix.format(cid=coord_node_id) + message.strip()

        # Mint a fresh session keyed by coord_node_id so the audit trail is
        # easy to navigate. The first directive creates; subsequent ones
        # to the same coord node reuse via the title.
        session_title = f"[direct:{coord_node_id}]"
        session_body = {"agent": target, "title": session_title}
        try:
            session_resp = poster(
                f"{vnext_base.rstrip('/')}/sessions",
                session_body,
                10.0,
            )
            session_id = session_resp["session_id"]
        except urllib.error.HTTPError as e:
            return {
                "error": "dispatch_failed",
                "message": f"session mint failed: HTTP {e.code}",
                "target": target,
                "coord_node_id": coord_node_id,
            }
        except Exception as e:
            return {
                "error": "dispatch_failed",
                "message": f"session mint failed: {type(e).__name__}: {e}",
                "target": target,
                "coord_node_id": coord_node_id,
            }

        chat_body = {"agent": target, "session_id": session_id, "message": wire_message}
        try:
            chat_resp = poster(
                f"{vnext_base.rstrip('/')}/chat",
                chat_body,
                dispatch_timeout_seconds,
            )
        except urllib.error.HTTPError as e:
            return {
                "error": "dispatch_failed",
                "message": f"chat dispatch failed: HTTP {e.code}",
                "target": target,
                "session_id": session_id,
                "coord_node_id": coord_node_id,
            }
        except Exception as e:
            return {
                "error": "dispatch_failed",
                "message": f"chat dispatch failed: {type(e).__name__}: {e}",
                "target": target,
                "session_id": session_id,
                "coord_node_id": coord_node_id,
            }

        limiter.record(sender=owner_agent, target=target, now=now)

        edge_id = None
        if edge_writer is not None:
            try:
                # The "message node" is the assistant's chat turn id. The
                # /chat response doesn't surface that directly today — use
                # the session_id as a stand-in until the route adds a
                # last_turn_id field. The lattice edge ties session → coord
                # node, still forensically useful.
                edge_id = edge_writer(coord_node_id, session_id, mode)
            except Exception:
                # Audit failure shouldn't tank the dispatch — the chat
                # already happened. Log and continue.
                edge_id = None

        return {
            "target": target,
            "session_id": session_id,
            "response_content": chat_resp.get("content", ""),
            "finish_reason": chat_resp.get("finish_reason", ""),
            "coord_node_id": coord_node_id,
            "edge_id": edge_id,
        }

    schema = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "enum": ["vett", "scotty"],
                "description": (
                    "Which peer agent to direct-message. Vett for research / "
                    "verification work; Scotty for execution / mechanical fixes. "
                    "You cannot direct-message yourself."
                ),
            },
            "message": {
                "type": "string",
                "description": (
                    "The instruction (mode=execute) or query (mode=query) "
                    "to send. Write it as you'd speak it — the tool adds "
                    "the framing prefix the peer reads as authoritative."
                ),
            },
            "coord_node_id": {
                "type": "string",
                "description": (
                    "REQUIRED. The Coordination node this directive is "
                    "anchored to. Every direct communication ties back to "
                    "a specific objective — no anchor, no message. This is "
                    "the structural constraint against managerial drift."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["execute", "query"],
                "description": (
                    "execute = 'do this now and report back' (default). "
                    "query = 'tell me your raw observations on this — skip "
                    "the polished report.' Same primitive, different framing."
                ),
                "default": "execute",
            },
        },
        "required": ["target", "message", "coord_node_id"],
        "additionalProperties": False,
    }

    return ToolSpec(
        name="direct_message_agent",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Send a directive or query directly to Vett or Scotty, anchored "
            "to a specific Coordination node. Use this when you need a peer "
            "to act or report without waiting for a heartbeat round-trip. "
            "Every call is forensically logged (lattice edge) and rate-capped."
        ),
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_direct_communication_tools.py -v`
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/direct_communication/tools.py \
        tests/test_direct_communication_tools.py
git commit -m "direct_communication: direct_message_agent tool (Delta 1)

Aetheria's push/pull primitive. Schema rejects missing coord_node_id at
the registry layer (loop-chatter defense). Both mode=execute and
mode=query flow through POST /chat with mode-specific framing prefix.
Lattice edge written per successful call (forensic trail). Rate limit
returns structured retry signal; chat dispatch failures return
structured dispatch_failed. All collaborators injectable for tests."
```

---

## Task 4: `NEEDS_DIRECTION` event kind + routing rule

**Files:**
- Modify: `soveryn/platform/coordination/events.py` (add CoordEventKind value)
- Modify: `soveryn/platform/coordination/routing.py` (add routing rule)
- Test: `tests/test_coord_routing.py` (existing flat test file)

- [ ] **Step 1: Write failing tests**

```python
def test_needs_direction_event_routes_to_aetheria():
    """Vett or Scotty raising NEEDS_DIRECTION pings Aetheria."""
    from soveryn.platform.coordination.events import CoordEvent, CoordEventKind
    from soveryn.platform.coordination.routing import route
    event = CoordEvent(
        id="e1", kind=CoordEventKind.NEEDS_DIRECTION,
        node_id="node-1", actor_agent="scotty",
        timestamp="2026-06-05T12:00:00",
        payload={"context_summary": "stuck",
                 "options_considered": ["a", "b"]},
        chain_depth=0,
    )
    assert route(event) == ("aetheria",)


def test_aetheria_cannot_raise_needs_direction_to_herself():
    """Self-filter — if Aetheria is somehow the actor, no routing."""
    from soveryn.platform.coordination.events import CoordEvent, CoordEventKind
    from soveryn.platform.coordination.routing import route
    event = CoordEvent(
        id="e1", kind=CoordEventKind.NEEDS_DIRECTION,
        node_id="node-1", actor_agent="aetheria",
        timestamp="2026-06-05T12:00:00", payload={}, chain_depth=0,
    )
    assert route(event) == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coord_routing.py -v -k "needs_direction"`
Expected: FAIL (enum value doesn't exist).

- [ ] **Step 3: Implement**

In `soveryn/platform/coordination/events.py`:

```python
class CoordEventKind(str, Enum):
    NODE_CREATED = "node_created"
    STATUS_CHANGED = "status_changed"
    PROMOTED = "promoted"
    BLOCK_ADDED = "block_added"
    ARCHIVED = "archived"
    NEEDS_DIRECTION = "needs_direction"  # NEW
```

In `soveryn/platform/coordination/routing.py`, add the rule inside `route()`:

```python
elif event.kind == CoordEventKind.NEEDS_DIRECTION:
    destinations.append("aetheria")
```

The existing self-filter at the bottom of `route()` already handles "Aetheria can't trigger herself."

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coord_routing.py -v`
Expected: PASS (no regressions + 2 new).

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/coordination/events.py \
        soveryn/platform/coordination/routing.py \
        tests/test_coord_routing.py
git commit -m "coord: NEEDS_DIRECTION event kind + routing to Aetheria

New CoordEventKind value for the peer-pings-Aetheria coordination path
(spec Delta 2). Routes to aetheria; self-filter prevents her from
triggering herself."
```

---

## Task 5: `request_direction` tool for Vett/Scotty

**Files:**
- Modify: `soveryn/platform/coordination/tools.py` (add new tool builder)
- Test: `tests/test_coord_tools.py` (existing flat test file)

- [ ] **Step 1: Write failing tests**

```python
def test_request_direction_emits_needs_direction_event(coord_store, event_bus):
    """Tool publishes a NEEDS_DIRECTION event with the brief + options."""
    from soveryn.platform.coordination.tools import build_request_direction_tool
    from soveryn.platform.coordination.events import CoordEventKind

    # Pre-create a coord node Scotty is referring to
    node = coord_store.create_node(
        board="Blueprint", title="port the foo module",
        owner="scotty", actor="aetheria",
    )

    tool = build_request_direction_tool(
        store=coord_store, event_bus=event_bus, owner_agent="scotty",
    )
    result = tool.handler({
        "node_id": node.id,
        "context_summary": "Two approaches diverge; need your call",
        "options_considered": ["full rewrite", "incremental"],
    })

    assert result["needs_direction_event_id"]
    events = event_bus.drain()
    assert len(events) == 1
    assert events[0].kind == CoordEventKind.NEEDS_DIRECTION
    assert events[0].node_id == node.id
    assert events[0].actor_agent == "scotty"
    assert events[0].payload["context_summary"] == "Two approaches diverge; need your call"
    assert events[0].payload["options_considered"] == ["full rewrite", "incremental"]


def test_request_direction_rejects_nonexistent_node(coord_store, event_bus):
    """node_id must point to a real coord node."""
    from soveryn.platform.coordination.tools import build_request_direction_tool
    tool = build_request_direction_tool(
        store=coord_store, event_bus=event_bus, owner_agent="scotty",
    )
    result = tool.handler({
        "node_id": "nonexistent-uuid",
        "context_summary": "x",
        "options_considered": ["a"],
    })
    assert result.get("error") == "unknown_node"


def test_request_direction_requires_at_least_one_option(coord_store, event_bus):
    """Empty options is a schema violation — if you have no options, you
    don't have a direction question, you have a panic."""
    from soveryn.platform.coordination.tools import build_request_direction_tool
    from soveryn.platform.tools.registry import ToolArgError
    node = coord_store.create_node(
        board="Blueprint", title="x", owner="scotty", actor="aetheria",
    )
    tool = build_request_direction_tool(
        store=coord_store, event_bus=event_bus, owner_agent="scotty",
    )
    with pytest.raises(ToolArgError, match="options_considered"):
        tool.handler({
            "node_id": node.id,
            "context_summary": "stuck",
            "options_considered": [],
        })
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_coord_tools.py -v -k "request_direction"`
Expected: FAIL (tool doesn't exist).

- [ ] **Step 3: Implement**

Append to `soveryn/platform/coordination/tools.py`:

```python
def build_request_direction_tool(
    *,
    store: CoordinationStore,
    event_bus,  # InMemoryEventBus
    owner_agent: str,
) -> ToolSpec:
    """Peer agent (Vett or Scotty) pings Aetheria for a judgment call on
    direction. Emits a NEEDS_DIRECTION CoordEvent — the webhook router
    auto-invokes Aetheria with the brief rendered into her prompt.

    Spec: docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md
    """

    def handler(args: Mapping[str, Any]) -> Any:
        node_id = args.get("node_id")
        context_summary = args.get("context_summary")
        options_considered = args.get("options_considered")

        if not isinstance(node_id, str) or not node_id.strip():
            raise ToolArgError("node_id must be a non-empty string")
        if not isinstance(context_summary, str) or not context_summary.strip():
            raise ToolArgError("context_summary must be a non-empty string")
        if (not isinstance(options_considered, list)
            or len(options_considered) == 0
            or not all(isinstance(o, str) for o in options_considered)):
            raise ToolArgError(
                "options_considered must be a non-empty list of strings — "
                "if you have no options, you have a panic, not a direction "
                "question. Spell out at least one path you've considered."
            )

        node = store.get_node(node_id)
        if node is None:
            return {"error": "unknown_node", "node_id": node_id}

        event = CoordEvent(
            id=str(uuid.uuid4()),
            kind=CoordEventKind.NEEDS_DIRECTION,
            node_id=node_id,
            actor_agent=owner_agent,
            timestamp=datetime.now().isoformat(),
            payload={
                "context_summary": context_summary,
                "options_considered": list(options_considered),
                "requester_agent": owner_agent,
            },
        )
        event_bus.put(event)
        return {
            "needs_direction_event_id": event.id,
            "node_id": node_id,
            "requester": owner_agent,
        }

    schema = {
        "type": "object",
        "properties": {
            "node_id": {
                "type": "string",
                "description": "The Coord node this request is anchored to.",
            },
            "context_summary": {
                "type": "string",
                "description": (
                    "Brief description of what you're stuck on. Aetheria "
                    "needs enough context to make a real call without "
                    "having to investigate from scratch."
                ),
            },
            "options_considered": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": (
                    "The paths you've considered. At least one — if you "
                    "have no options, this isn't a direction request, "
                    "it's a panic."
                ),
            },
        },
        "required": ["node_id", "context_summary", "options_considered"],
        "additionalProperties": False,
    }
    return ToolSpec(
        name="request_direction",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Ping Aetheria for a judgment call on direction. Use this when "
            "you've hit a wall that needs a decision on what to do next — "
            "not a technical fix you can solve, but a strategic call. "
            "Lay out the brief and the options you've considered."
        ),
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_coord_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/coordination/tools.py tests/test_coord_tools.py
git commit -m "coord: request_direction tool for Vett/Scotty (Delta 2)

Peer agents emit NEEDS_DIRECTION CoordEvents via this tool when they
need Aetheria's judgment on direction. Schema requires at least one
option_considered — no panics, only structured requests."
```

---

## Task 6: Webhook dispatcher render for NEEDS_DIRECTION

**Files:**
- Modify: `soveryn/platform/coordination/dispatcher.py` (extend `build_webhook_prompt`)
- Test: `tests/test_coord_dispatcher.py` (existing flat test file — verify)

- [ ] **Step 1: Find the existing build_webhook_prompt to extend**

Read `soveryn/platform/coordination/dispatcher.py` first to see the current `build_webhook_prompt` signature + branching.

- [ ] **Step 2: Write failing test**

```python
def test_build_webhook_prompt_renders_needs_direction():
    """Aetheria's webhook prompt for a NEEDS_DIRECTION event includes the
    coord_node_id, requester, context_summary, options, and the explicit
    callout to use direct_message_agent to respond."""
    from soveryn.platform.coordination.events import CoordEvent, CoordEventKind
    from soveryn.platform.coordination.dispatcher import build_webhook_prompt
    event = CoordEvent(
        id="e1", kind=CoordEventKind.NEEDS_DIRECTION,
        node_id="node-42", actor_agent="scotty",
        timestamp="2026-06-05T12:00:00",
        payload={
            "context_summary": "Migration is hung on schema diff",
            "options_considered": ["rewrite migration", "manual fix"],
            "requester_agent": "scotty",
        },
        chain_depth=0,
    )
    prompt = build_webhook_prompt(event)
    assert "NEEDS_DIRECTION" in prompt
    assert "node-42" in prompt
    assert "scotty" in prompt
    assert "Migration is hung on schema diff" in prompt
    assert "rewrite migration" in prompt
    assert "manual fix" in prompt
    assert "direct_message_agent" in prompt
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_coord_dispatcher.py -v -k "needs_direction"`
Expected: FAIL.

- [ ] **Step 4: Implement**

Extend `build_webhook_prompt` in `dispatcher.py` with a new branch on `event.kind == CoordEventKind.NEEDS_DIRECTION`. Render template per the spec:

```python
elif event.kind == CoordEventKind.NEEDS_DIRECTION:
    requester = event.payload.get("requester_agent", event.actor_agent)
    summary = event.payload.get("context_summary", "")
    options = event.payload.get("options_considered", [])
    options_block = "\n".join(f"  - {opt}" for opt in options)
    return (
        f"[NEEDS_DIRECTION at coord:{event.node_id}]\n"
        f"{requester} paused for your decision.\n\n"
        f"Context: {summary}\n\n"
        f"Options considered:\n{options_block}\n\n"
        f"Use direct_message_agent(target='{requester}', mode='execute', "
        f"coord_node_id='{event.node_id}', message='<your decision>') "
        f"to instruct them on which way to go."
    )
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_coord_dispatcher.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add soveryn/platform/coordination/dispatcher.py tests/test_coord_dispatcher.py
git commit -m "coord/dispatcher: NEEDS_DIRECTION webhook prompt template

Aetheria's incoming prompt for a peer's direction request — renders the
coord node, requester, brief, options, and the explicit
direct_message_agent invocation she should use to respond."
```

---

## Task 7: Startup wiring + integration smoke

**Files:**
- Modify: `soveryn/app/startup.py` (register both tools on the right agents)
- Test: `tests/test_app_startup_direct_communication.py` (new)

- [ ] **Step 1: Write failing test**

```python
def test_direct_message_agent_registered_for_aetheria(app_state):
    """Tool registry has direct_message_agent on Aetheria, not on Vett/Scotty."""
    registry = app_state["tool_registry"]
    aetheria_tools = {t.name for t in registry.tools_for_agent("aetheria")}
    vett_tools = {t.name for t in registry.tools_for_agent("vett")}
    scotty_tools = {t.name for t in registry.tools_for_agent("scotty")}
    assert "direct_message_agent" in aetheria_tools
    assert "direct_message_agent" not in vett_tools
    assert "direct_message_agent" not in scotty_tools


def test_request_direction_registered_for_vett_and_scotty(app_state):
    """request_direction lives on the peers, not on Aetheria."""
    registry = app_state["tool_registry"]
    aetheria_tools = {t.name for t in registry.tools_for_agent("aetheria")}
    vett_tools = {t.name for t in registry.tools_for_agent("vett")}
    scotty_tools = {t.name for t in registry.tools_for_agent("scotty")}
    assert "request_direction" not in aetheria_tools
    assert "request_direction" in vett_tools
    assert "request_direction" in scotty_tools
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app_startup_direct_communication.py -v`
Expected: FAIL.

- [ ] **Step 3: Wire in startup.py**

Locate the existing tool-registration block (around the signal_send registration site). Add:

```python
# Direct Agent Communication (Delta 1 + Delta 2)
from soveryn.agents.direct_communication.tools import build_direct_message_agent_tool
from soveryn.platform.coordination.tools import build_request_direction_tool
from soveryn.platform.lattice.legacy import record_direct_communication_edge

# Aetheria's direct rail to peers
def _direct_edge_writer(coord_node_id, message_node_id, mode):
    return record_direct_communication_edge(
        store=lattice_store,
        coord_node_id=coord_node_id,
        message_node_id=message_node_id,
        mode=mode,
    )

tool_registry.register(build_direct_message_agent_tool(
    owner_agent="aetheria",
    edge_writer=_direct_edge_writer,
    vnext_base=env.vnext_base,
))

# Peers' upward channel for judgment calls
for peer in ("vett", "scotty"):
    tool_registry.register(build_request_direction_tool(
        store=coord_store,
        event_bus=coord_event_bus,
        owner_agent=peer,
    ))
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_app_startup_direct_communication.py -v`
Expected: PASS.

Full suite: `pytest tests/ -q` — expected no regressions.

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/startup.py tests/test_app_startup_direct_communication.py
git commit -m "startup: wire direct_message_agent + request_direction tools

direct_message_agent registered only for Aetheria; request_direction
registered for both Vett and Scotty (not Aetheria — she's the
recipient of those pings, not a sender). Edge writer wraps the
lattice helper so it can be injected for unit tests."
```

---

## Task 8: End-to-end manual verification with Jon + Aetheria

**Files:** human-in-the-loop, no code

- [ ] **Step 1: Restart vnext to load the new tools**

```bash
systemctl --user restart soveryn-vnext.service
sleep 4
systemctl --user is-active soveryn-vnext.service
```

- [ ] **Step 2: Push verification — Aetheria directs Vett**

In Aetheria's chat:
> "Direct Vett to summarize the last three Friction nodes on the board. Anchor it to coord node <pick a real id from her board>."

Expected:
- Aetheria calls `direct_message_agent(target="vett", mode="execute", coord_node_id=..., message=...)`
- Vett's chat session `[direct:<node_id>]` shows the directive arrived with the `[DIRECTIVE FROM AETHERIA...]` prefix
- Vett's response surfaces back to Aetheria's tool result
- Lattice has a `direct_command` edge tying the session → coord node

- [ ] **Step 3: Pull verification — Aetheria queries Scotty**

In Aetheria's chat:
> "Query Scotty for his current internal observations on the migration arc. Anchor it to coord node <pick a real id>."

Expected:
- `direct_message_agent(target="scotty", mode="query", coord_node_id=..., message=...)` fires
- Scotty's session sees the `[QUERY FROM AETHERIA...]` prefix
- His response is raw observations, not a polished report
- Lattice has a `direct_query` edge

- [ ] **Step 4: Coordination verification — Scotty pings Aetheria**

In Scotty's chat (or via a coord webhook scenario):
> "You hit a wall on coord node X — call request_direction with the brief and options."

Expected:
- `request_direction(...)` emits a NEEDS_DIRECTION CoordEvent
- Webhook router fires; dispatcher writes the rendered prompt into Aetheria's webhook session
- Aetheria sees the formatted "NEEDS_DIRECTION at coord:..." prompt with the brief + options
- Aetheria responds via `direct_message_agent(target="scotty", mode="execute", coord_node_id=...)`
- The cycle closes; Scotty receives the decision

- [ ] **Step 5: Loop-chatter constraint verification**

In Aetheria's chat:
> "Try to direct-message Vett without a coord_node_id."

Expected:
- Tool registry raises `ToolArgError` at the schema layer
- Aetheria sees: `"coord_node_id is required — every direct communication must be tied to a Coordination node..."`
- She cannot bypass.

- [ ] **Step 6: Rate-limit verification (optional, if time)**

In Aetheria's chat:
> "Send 10 direct messages to Vett in quick succession (loop or batch)."

Expected:
- First 8 succeed
- 9th and 10th return `{"error": "rate_limited", "retry_after_seconds": <n>}`
- She sees the structured signal and can wait

- [ ] **Step 7: Save memory + handoff**

Write a `project_soveryn_direct_agent_communication_shipped.md` memory documenting:
- Aetheria has a direct rail to Vett + Scotty
- Loop-chatter constraint at schema layer (coord_node_id required)
- DSL substrate is now in place
- Any production bugs caught during T8 (apply the same "tests fabricate vs production shape" check as the signal-images build)
