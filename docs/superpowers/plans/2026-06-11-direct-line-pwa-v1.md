# SOVERYN Direct Line PWA — v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a mobile-first Direct Line PWA that gives Jon a SOVERYN-owned phone rail to Aetheria: authenticated device pairing, retrying local outbox, text/image send, streamed replies, and revocation. Signal remains fallback; Direct Line v1 is text/image only. No push notifications, no voice calls.

**Architecture:** `soveryn/app/routes/direct.py` owns Direct Line transport/auth/receipts. It must call the same AgentLoop-backed chat path as `/chat` and `/chat_stream`; it must not write raw turns into `conversations_vnext.db`. The phone PWA stores a device secret and local outbox, sends with stable `client_msg_id`, and parses POST-backed SSE from `/direct/send_stream`.

**Linked spec:** `docs/superpowers/specs/2026-06-11-direct-line-pwa-design.md`

**Non-negotiable rule:** Direct Line is a transport adapter. It may authenticate, queue, retry, and stream. It may not become a second chat engine.

---

## Task 1: Preflight + Branch

**Files:** none

- [ ] **Step 1: Check worktree**

Run:

```bash
cd ~/soveryn_vnext
git status --short
```

Expected before implementation: no unexpected tracked modifications under `soveryn/` or `tests/`. If Claude's Harness work is still in progress, either finish that arc or branch from a clean checkpoint. Do not stash or discard unrelated work.

- [ ] **Step 2: Cut branch**

```bash
git checkout main
git pull --ff-only
git checkout -b direct-line-pwa-v1
```

---

## Task 2: Direct Line Store + Schema

**Files:**
- Create: `soveryn/platform/direct_line/__init__.py`
- Create: `soveryn/platform/direct_line/store.py`
- Test: `tests/test_direct_line_store.py`
- Modify: DB initialization path used by vNext startup

- [ ] **Step 1: Write failing tests**

Cover:
- `ensure_schema()` creates `direct_devices`, `direct_pairing_tokens`, `direct_message_receipts`
- pairing token can be created, consumed once, and expires
- device secret is stored hashed, not raw
- revoked device fails lookup
- receipt upsert is unique by `(device_id, client_msg_id)`

- [ ] **Step 2: Implement store**

Use sqlite directly, matching existing vNext store style. Keep all timestamps ISO strings.

Required API:

```python
class DirectLineStore:
    def ensure_schema(self) -> None: ...
    def create_pairing_token(self, *, label: str, ttl_seconds: int = 600) -> PairingToken: ...
    def consume_pairing_token(self, token: str) -> PairedDevice: ...
    def authenticate_device(self, secret: str) -> DirectDevice | None: ...
    def revoke_device(self, device_id: str) -> bool: ...
    def list_devices(self) -> tuple[DirectDevice, ...]: ...
    def upsert_receipt(self, *, device_id: str, client_msg_id: str, session_id: str, status: str, error: str | None = None) -> DirectReceipt: ...
    def get_receipt(self, *, device_id: str, client_msg_id: str) -> DirectReceipt | None: ...
```

Security rules:
- use `secrets.token_urlsafe(32)` or stronger
- store only hashes
- compare with `hmac.compare_digest`
- use a server-side pepper from env/config; if absent in dev, derive a stable local-only dev pepper and log a warning

- [ ] **Step 3: Wire schema creation into startup**

At app startup, instantiate the store against the vNext memory DB and call `ensure_schema()`. Expose it through `current_app.extensions["soveryn"]["direct_line_store"]`.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_direct_line_store.py -v
```

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/direct_line tests/test_direct_line_store.py soveryn/app/startup.py
git commit -m "feat(direct-line): add device auth and receipt store"
```

---

## Task 3: Factor Shared Chat Dispatch Helpers

**Files:**
- Modify: `soveryn/app/routes/chat.py`
- Test: existing chat route tests, plus `tests/test_direct_line_chat_helpers.py`

This is the key architecture gate. Direct Line must reuse the same chat behavior without copy/pasting route logic or writing DB turns itself.

- [ ] **Step 1: Write tests for helper behavior**

Add tests around helper functions, not Direct Line routes yet:
- sync helper calls `loop.process_message(session_id, message, attachments=...)`
- stream helper prefetches first event before opening SSE, preserving current `/chat_stream` setup-error behavior
- helper maps `AgentLoopError`, `LlamaServerTimeout`, `LlamaServerError`, and `RoutingError` to the same error codes as today
- current `/chat` and `/chat_stream` tests still pass unchanged

- [ ] **Step 2: Extract helpers**

In `soveryn/app/routes/chat.py`, factor route internals into reusable functions. Suggested names:

```python
def dispatch_chat_sync(*, agent: str, session_id: str, message: str, attachments: tuple[str, ...] | None) -> tuple[dict, int]: ...
def open_chat_stream(*, agent: str, session_id: str, message: str, attachments: tuple[str, ...] | None) -> Response | tuple[Response, int]: ...
```

Keep `_validate_attachments`, `_event_to_dict`, and `_sse` importable for Direct Line, or move shared pieces to `soveryn/app/services/chat_dispatch.py` if that keeps `routes/chat.py` cleaner.

- [ ] **Step 3: Prove no behavior drift**

Run existing chat tests and a manual smoke:

```bash
pytest tests -q -k "chat or agent_loop_history_budget"
curl -sS http://127.0.0.1:5001/health
```

- [ ] **Step 4: Commit**

```bash
git add soveryn/app/routes/chat.py tests/test_direct_line_chat_helpers.py
git commit -m "refactor(chat): expose shared dispatch helpers for Direct Line"
```

---

## Task 4: Direct Line Routes — Pairing, Auth, Admin

**Files:**
- Create: `soveryn/app/routes/direct.py`
- Modify: `soveryn/app/startup.py`
- Test: `tests/test_direct_line_auth.py`

- [ ] **Step 1: Write failing route tests**

Cover:
- `POST /direct/admin/pairing-tokens` works only under localhost/admin guard
- `POST /direct/pair` consumes valid token and returns `device_id`, `device_secret`, `label`
- pairing token cannot be reused
- missing/invalid bearer token returns `401`
- revoked device returns `401`
- `GET /direct/admin/devices` lists devices without secrets
- `POST /direct/admin/devices/<id>/revoke` revokes a device

- [ ] **Step 2: Implement `direct.py` auth helpers**

Required helpers:

```python
def require_direct_device() -> DirectDevice | tuple[Response, int]: ...
def direct_error(code: str, message: str, status: int): ...
```

Bearer parsing:
- require `Authorization: Bearer <secret>`
- no token in query string
- no localhost bypass for phone APIs

- [ ] **Step 3: Register blueprint**

Register `direct_bp` in `_register_blueprints(app)`.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_direct_line_auth.py -v
```

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/routes/direct.py soveryn/app/startup.py tests/test_direct_line_auth.py
git commit -m "feat(direct-line): add pairing and device-auth routes"
```

---

## Task 5: Direct Line Send Routes + Idempotency

**Files:**
- Modify: `soveryn/app/routes/direct.py`
- Test: `tests/test_direct_line_routes.py`
- Test: `tests/test_direct_line_idempotency.py`

- [ ] **Step 1: Write failing route tests**

Cover:
- authenticated `POST /direct/messages` resolves/creates `[direct] <device label>` Aetheria session
- authenticated `POST /direct/send_stream` returns `text/event-stream`
- Direct routes call shared chat helpers, not `conv_store.save_turn`
- attachments pass through existing validator
- invalid image payload returns `invalid_attachments`
- duplicate delivered `client_msg_id` does not call Aetheria again
- duplicate in-progress `client_msg_id` returns a clear conflict or safe retry behavior

- [ ] **Step 2: Define v1 idempotency strictly**

Use this v1 rule unless implementation evidence forces a change:
- before dispatch: receipt `received`
- when stream starts: receipt `streaming`
- on `done`: receipt `delivered`
- on setup/terminal error: receipt `failed`
- retry of `delivered`: no re-run; return a compact ACK/done replay event
- retry of `failed`: allowed; re-run and update receipt
- retry of `streaming`: return `409 duplicate_message_conflict` unless the implementation can prove the prior stream died before an assistant turn saved

This is conservative and prevents duplicate Aetheria turns.

- [ ] **Step 3: Implement session resolution**

Per device, resolve latest session:

```text
agent = "aetheria"
title = "[direct] <device label>"
```

If absent, create via `conv_store.new_session("aetheria", title=title)` or the same app-level helper as `/sessions`.

- [ ] **Step 4: Implement routes**

`POST /direct/messages` calls sync helper.

`POST /direct/send_stream` wraps the shared stream response so receipt status can be marked `delivered` when a `done` event is observed and `failed` when an error event/setup exception occurs. Do not change the SSE event schema except for optional Direct Line ACK events before chat tokens:

```json
{"type":"ack","client_msg_id":"...","status":"streaming"}
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_direct_line_routes.py tests/test_direct_line_idempotency.py -v
```

- [ ] **Step 6: Commit**

```bash
git add soveryn/app/routes/direct.py tests/test_direct_line_routes.py tests/test_direct_line_idempotency.py
git commit -m "feat(direct-line): add authenticated send routes with idempotent receipts"
```

---

## Task 6: PWA Shell + Static Assets

**Files:**
- Create: `soveryn/app/templates/direct.html`
- Create: `soveryn/static/direct/direct.css`
- Create: `soveryn/static/direct/direct.js`
- Create: `soveryn/static/direct/manifest.webmanifest`
- Create: `soveryn/static/direct/service-worker.js`
- Modify: `soveryn/app/routes/direct.py`
- Test: `tests/test_direct_line_pwa.py`

- [ ] **Step 1: Write failing asset tests**

Cover:
- `GET /direct` returns HTML shell
- manifest route/static file is reachable
- JS and CSS are reachable
- service worker is reachable if included
- HTML includes mobile viewport and manifest link

- [ ] **Step 2: Build mobile-first UI**

UI requirements:
- one screen, chat log, composer, image attach, send
- no marketing/landing copy
- stable fixed composer at bottom
- visible connection state
- message status chips/icons: queued, sending, retrying, delivered, failed
- attachment preview before send

Use plain HTML/CSS/JS; no new frontend framework.

- [ ] **Step 3: Implement client auth state**

Client stores:
- `direct.device_id`
- `direct.device_secret`
- `direct.label`

If no secret is present, show pairing-token input. Pairing QR scan can be a v1.1 convenience; v1 supports opening `/direct/pair/<token>` or entering a code manually.

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_direct_line_pwa.py -v
```

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/templates/direct.html soveryn/static/direct soveryn/app/routes/direct.py tests/test_direct_line_pwa.py
git commit -m "feat(direct-line): add mobile PWA shell"
```

---

## Task 7: Client Outbox + Streaming Parser

**Files:**
- Modify: `soveryn/static/direct/direct.js`
- Test: browser/manual; optional JS syntax check

- [ ] **Step 1: Implement local outbox**

Use LocalStorage for v1 unless payload size from images forces IndexedDB. Store:

```json
{
  "client_msg_id": "...",
  "message": "...",
  "attachments": [],
  "status": "queued|sending|retrying|delivered|failed",
  "attempts": 0,
  "created_at": "...",
  "updated_at": "..."
}
```

- [ ] **Step 2: Implement send + SSE parse**

`send_stream` behavior:
- create outbox item before network call
- POST to `/direct/send_stream`
- parse `data: {...}\n\n` chunks
- append streamed assistant tokens into one live assistant bubble
- mark user item delivered only after `done`
- on network error, leave item retryable

- [ ] **Step 3: Implement retry**

Retry rules:
- retry queued/failed items manually
- auto-retry retryable items on page load and `online` event
- capped exponential backoff
- no duplicate `client_msg_id`

- [ ] **Step 4: Syntax check**

```bash
node --check soveryn/static/direct/direct.js
```

- [ ] **Step 5: Commit**

```bash
git add soveryn/static/direct/direct.js
git commit -m "feat(direct-line): add retrying phone outbox and SSE client"
```

---

## Task 8: End-to-End Integration Smoke

**Files:**
- Test: `tests/test_direct_line_integration.py`
- Optional: `scripts/direct_line_pair.py`

- [ ] **Step 1: Write opt-in integration test**

Marked `@pytest.mark.integration`, requires live vNext and router.

Flow:
1. mint pairing token
2. pair fake device
3. call `/direct/send_stream` with `client_msg_id`
4. assert SSE contains `ack` and terminal `done` or structured `error`
5. assert receipt row updated
6. retry same `client_msg_id`; assert no second Aetheria call for delivered case

- [ ] **Step 2: Run unit suite**

```bash
pytest tests/test_direct_line_*.py -v
```

- [ ] **Step 3: Run integration**

```bash
pytest tests/test_direct_line_integration.py -v --run-integration
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_direct_line_integration.py scripts/direct_line_pair.py
git commit -m "test(direct-line): end-to-end authenticated stream smoke"
```

---

## Task 9: Phone Shakedown + Notes

**Files:**
- Create: `docs/notes/2026-06-XX-direct-line-v1-shakedown.md`

- [ ] **Step 1: Start/restart vNext**

Use the existing service or dev server. Confirm:

```bash
curl -sS http://127.0.0.1:5001/health
```

- [ ] **Step 2: Pair real phone**

Mint a pairing token from localhost/admin route. Open `/direct` from phone over the chosen reachable HTTPS/LAN path. Store the returned device secret on the phone only.

- [ ] **Step 3: Manual test matrix**

Record results:
- text message sends and streams reply
- image message sends and Aetheria sees image
- airplane mode during send -> item remains queued/retryable
- network restored -> retry succeeds
- duplicate retry does not duplicate delivered turn
- revoke device -> phone API calls fail
- Signal remains untouched

- [ ] **Step 4: Write shakedown note**

Include:
- URL/path used
- device label
- tests passed/failed
- latency notes
- known issues
- whether v1 is good enough to use as primary phone rail for one day

- [ ] **Step 5: Commit**

```bash
git add docs/notes/2026-06-XX-direct-line-v1-shakedown.md
git commit -m "docs(direct-line): v1 phone shakedown results"
```

---

## Deferred

- Push notifications
- Aetheria-initiated wake-up events
- Incoming call UX
- WebRTC voice over Direct Line
- Native app shell
- End-to-end payload encryption above HTTPS

---

## Self-Review

**Spec coverage:** Auth, pairing, revocation, send routes, streaming, outbox, idempotency, PWA shell, tests, and phone shakedown are covered.

**Scope discipline:** No Signal bridge changes, no router changes, no voice/push work, no second chat engine.

**Risk gates:** Task 3 gates shared dispatch extraction; Task 5 gates idempotency semantics before client retry depends on it.

**Success bar:** Jon can use `/direct` from phone for normal text/image Aetheria conversation without Signal, with owned retry/status behavior.
