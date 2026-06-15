# SOVERYN Direct Line PWA — Design

**Date:** 2026-06-11
**Status:** Draft — ready for implementation-plan review
**Origin:** Signal diagnostic showed bot outbound works but phone replies do not reach the bot account's Signal server queue. Signal must become optional, not load-bearing.

## What this is

Build a SOVERYN-owned private phone rail for Jon ↔ Aetheria as a mobile-first PWA. The app bypasses Signal's account/device delivery machinery and talks directly to vNext over authenticated HTTPS.

Signal remains available as a convenience rail, but Direct Line becomes the primary phone surface because its delivery, retry, logging, and failure states are under our control.

## Goal

Jon can open `/direct` on his phone, send Aetheria text/images/audio-note metadata through SOVERYN-owned routes, receive streamed replies, and survive poor cell service via a local retrying outbox. Messages enter the same Aetheria chat path as `/chat` / `/chat_stream`; Direct Line is a transport adapter, not a second conversation engine.

## Scope

### In
- Mobile-first installable PWA at `/direct`
- Device-token authentication with revocable devices
- Pairing-token or QR bootstrap flow from localhost/admin surface
- Durable per-device Direct Line session titled `[direct] <device label>`
- Authenticated text + image message send
- Streaming reply path using a POST-backed SSE response, same shape as `/chat_stream`
- LocalStorage or IndexedDB outbox with retry and server ACKs
- Connection state in the UI: online/offline, sending, retrying, delivered, failed
- Server-side audit rows for direct messages and delivery attempts
- Tests for auth, replay/idempotency, session ownership, route plumbing, and UI assets

### Out
- Native iOS/Android app
- App Store / TestFlight distribution
- Push notifications
- Background audio recording/upload
- Multi-user chat or arbitrary public access
- Replacing the existing desktop chat UI
- Replacing Signal immediately; Signal becomes fallback/legacy after Direct Line works
- Direct writes into `conversations_vnext.db` from the route layer

## Non-negotiable boundary

Direct Line routes must not write raw turns directly into the conversations DB. They must call the same application-level chat path used by `/chat` / `/chat_stream`, or a factored helper extracted from `soveryn/app/routes/chat.py`.

Reason: persistence, attachments, lattice recording, salience, continuity, tool behavior, context budgeting, and error semantics must stay identical across UI, voice, Signal, and Direct Line. Direct Line owns transport/auth/retry only.

## User experience

Jon visits:

```text
https://<soveryn-host>/direct
```

First device setup:

1. Jon opens a localhost/admin pairing page on the workstation.
2. SOVERYN shows a short-lived pairing QR or one-time code.
3. Phone opens `/direct/pair/<token>` or scans QR.
4. Server mints a device secret once, stores only a hash, and the phone stores the secret locally.
5. Future requests authenticate with `Authorization: Bearer <device_secret>`.

Daily use:

1. Phone opens `/direct`.
2. UI shows the current Direct Line thread.
3. Jon sends a message.
4. Message enters local outbox with a stable `client_msg_id`.
5. UI POSTs to `/direct/send_stream`.
6. Server ACKs and streams Aetheria's reply tokens.
7. On network loss, unsent outbox items retry with backoff. Duplicate POSTs are idempotent by `client_msg_id`.

## Data model

Add tables to the vNext memory DB initialization path.

### `direct_devices`

```sql
CREATE TABLE IF NOT EXISTS direct_devices (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    revoked_at TEXT
);
```

### `direct_pairing_tokens`

```sql
CREATE TABLE IF NOT EXISTS direct_pairing_tokens (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);
```

### `direct_message_receipts`

```sql
CREATE TABLE IF NOT EXISTS direct_message_receipts (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES direct_devices(id),
    client_msg_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(device_id, client_msg_id)
);
```

`status`: `received`, `streaming`, `delivered`, `failed`.

The receipt table is not the source of conversation truth. It exists for phone retry/idempotency and diagnostics.

## Server routes

Create `soveryn/app/routes/direct.py` and register it in `soveryn/app/startup.py`.

### `GET /direct`

Serves the PWA shell:

- `soveryn/app/templates/direct.html`
- `soveryn/static/direct/direct.css`
- `soveryn/static/direct/direct.js`
- `soveryn/static/direct/manifest.webmanifest`
- optional service worker at `soveryn/static/direct/service-worker.js`

Unauthenticated devices may load the shell, but API calls require a token.

### `POST /direct/pair`

Consumes a short-lived pairing token and returns:

```json
{
  "device_id": "...",
  "device_secret": "...",
  "label": "Jon iPhone"
}
```

The secret is shown once. Server stores only `sha256(secret + server_pepper)`.

### `POST /direct/send_stream`

Authenticated POST. Returns SSE using the same event schema as `/chat_stream`.

Request:

```json
{
  "client_msg_id": "uuid-from-phone",
  "message": "text from Jon",
  "attachments": ["data:image/jpeg;base64,..."]
}
```

Server behavior:

1. Authenticate device.
2. Upsert `direct_message_receipts(device_id, client_msg_id)`.
3. Resolve or create a durable Aetheria session titled `[direct] <device label>`.
4. Call the same stream helper as `/chat_stream` with:
   - `agent = "aetheria"`
   - resolved `session_id`
   - user `message`
   - optional image `attachments`
5. Stream `token`, `tool_call`, `tool_result`, `done`, and `error` events unchanged.
6. Mark receipt `delivered` on `done`, `failed` on setup/stream error.

Idempotency:

- If `(device_id, client_msg_id)` already has `delivered`, return a compact SSE sequence with an ACK/done replay marker and do not re-run Aetheria.
- If status is `received` or `streaming` and the original request died, allow retry to re-run only if no assistant turn was saved for that receipt. The implementation plan must define this check concretely.

### `POST /direct/messages`

Authenticated non-streaming fallback for poor browsers or debugging. Same request body as `/direct/send_stream`; returns:

```json
{
  "client_msg_id": "...",
  "status": "delivered",
  "content": "Aetheria reply",
  "session_id": "..."
}
```

Internally calls the same helper as `/chat`.

### `GET /direct/stream`

Authenticated SSE status stream for connection heartbeat and future out-of-band events.

v1 events:

```json
{"type":"hello","device_id":"..."}
{"type":"heartbeat","ts":"..."}
```

Deferred events:

- Aetheria spontaneous Direct Line messages
- push handoff notifications
- server-side retry status

Do not block v1 on deferred events.

### Admin routes

Localhost-only or existing admin guard:

- `POST /direct/admin/pairing-tokens` — mint QR/code
- `GET /direct/admin/devices` — list devices
- `POST /direct/admin/devices/<id>/revoke` — revoke a device

## Authentication

Device secrets are bearer tokens with these rules:

- Generated with `secrets.token_urlsafe(32)` or stronger
- Stored only as a salted/peppered hash
- Compared with `hmac.compare_digest`
- Revoked devices return `401`
- Missing/invalid tokens return `401`
- Direct APIs never fall back to localhost trust for phone requests

Pairing tokens:

- Short-lived, default 10 minutes
- One-time use
- Stored hashed
- Consumed atomically

## PWA frontend

Files:

- `soveryn/app/templates/direct.html`
- `soveryn/static/direct/direct.css`
- `soveryn/static/direct/direct.js`
- `soveryn/static/direct/manifest.webmanifest`
- `soveryn/static/direct/service-worker.js` (optional v1 cache shell only)

UI requirements:

- Mobile-first, one conversation screen, no marketing page
- Dense but comfortable chat surface
- Composer with text area, send button, image attach button
- Attachment previews before send
- Per-message status: queued, sending, retrying, delivered, failed
- Connection indicator
- Manual retry button for failed messages
- Local outbox persisted in LocalStorage or IndexedDB
- No visible implementation instructions or explanatory copy in the app UI

Client behavior:

- Generate `client_msg_id` before network send
- Store pending item before POST
- Use `fetch()` streaming reader to parse SSE from `/direct/send_stream`
- Retry unsent items with capped exponential backoff
- Respect `navigator.onLine` but do not rely on it exclusively
- Keep auth secret in local storage for v1; native secure storage is deferred to native app

## Attachment policy

Reuse the existing `/chat` attachment validator:

- Aetheria only
- `data:image/*;base64,...`
- accepted MIME set from `soveryn/platform/vision_types.py`
- same size caps as `/chat` / `/chat_stream`

Direct Line should not introduce a second attachment policy.

## Error model

API errors use the existing vNext error shape where possible:

```json
{
  "error": {
    "code": "invalid_token",
    "message": "..."
  }
}
```

Required codes:

- `missing_token`
- `invalid_token`
- `revoked_device`
- `expired_pairing_token`
- `invalid_pairing_token`
- `duplicate_message_conflict`
- `invalid_message`
- `invalid_attachments`
- `chat_timeout`
- `chat_server_error`

## Observability

Every Direct Line request should leave enough trail to answer:

- Did the phone send it?
- Did the server authenticate it?
- Did SOVERYN accept it?
- Did Aetheria start processing?
- Did an assistant turn save?
- Did the phone receive the streamed `done`?

Minimum logging:

- device id, never token
- `client_msg_id`
- receipt status transitions
- session id
- setup errors
- stream terminal state

## Security notes

- Direct Line is private single-user infrastructure, but it is reachable from a phone. Treat it as internet-facing once exposed beyond localhost.
- Require HTTPS before using it off LAN.
- Do not log bearer tokens.
- Do not store raw pairing tokens.
- Do not expose `/direct/admin/*` outside localhost/admin guard.
- Add simple per-device rate limiting before exposing over WAN.
- Add `Cache-Control: no-store` on authenticated API responses.

## Implementation files

**New:**

- `soveryn/app/routes/direct.py`
- `soveryn/app/templates/direct.html`
- `soveryn/static/direct/direct.css`
- `soveryn/static/direct/direct.js`
- `soveryn/static/direct/manifest.webmanifest`
- `soveryn/static/direct/service-worker.js`
- `tests/test_direct_line_auth.py`
- `tests/test_direct_line_routes.py`
- `tests/test_direct_line_idempotency.py`

**Modified:**

- `soveryn/app/startup.py` — register direct blueprint
- `soveryn/app/routes/chat.py` — factor shared sync/stream dispatch helpers if needed
- DB initialization path for memory/conversation tables — create Direct Line tables

**Not modified:**

- `soveryn/agents/signal_bridge/*` for v1
- router presets
- AgentLoop semantics except through already-supported chat/stream calls
- Vett/Scotty/heartbeat/dream surfaces

## Verification

Unit:

- Pairing token cannot be reused
- Revoked device cannot call APIs
- Invalid bearer token rejected
- `client_msg_id` duplicate is idempotent
- Direct route resolves a `[direct]` Aetheria session
- Direct route calls shared chat/stream helper, not DB writes
- Attachment validation matches `/chat_stream`

Integration:

- `POST /direct/send_stream` streams at least one token and a `done` event against live vNext
- Network-aborted client can retry a pending outbox item without duplicating a delivered turn
- `/direct/stream` emits heartbeat events
- PWA shell loads on mobile viewport

Manual:

- Install PWA on phone
- Pair device by QR/code
- Send text
- Send image
- Toggle phone network off during send, then back on; outbox retries
- Revoke device and confirm further sends fail

## Success bar

Direct Line v1 succeeds when Jon can use the phone PWA as the primary Aetheria rail for normal text/image conversation for one full day without touching Signal, and failures are visible as owned retry/status states instead of opaque third-party delivery gaps.

## Future work

- Push notifications
- Audio note capture and transcription
- End-to-end encrypted payloads on top of HTTPS
- Native iOS shell if PWA background behavior is insufficient
- Aetheria-initiated spontaneous Direct Line messages
- Multi-device thread merge controls
- Replace Signal bridge with Direct Line fallback routing

## See also

- `docs/superpowers/specs/2026-06-05-signal-images-design.md`
- `soveryn/app/routes/chat.py`
- `soveryn/agents/signal_bridge/daemon.py`
- Signal diagnostic, 2026-06-11: outbound bot-to-phone works; phone-to-bot receive queue stays empty.
