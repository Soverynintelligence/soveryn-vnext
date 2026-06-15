# Messenger Phase 1 — Handoff

Phase 1 lands the vnext-side substrate: schema, pairing, auth, threads,
envelope shapes, idempotency, basic send/receive wired to AgentLoop.
PWA shell renders the pairing screen + thread list + compose with
Aetheria's Terminal-meets-Luxury design contract intact (Void-Gold
accent, Sovereign Edge, asymmetric weight). End-to-end smoke green.

## What works today

- Pairing flow (QR/code + claim)
- Device bearer auth + revocation
- Multi-agent thread creation (Aetheria/Vett/Scotty)
- Idempotent message send via client_msg_id
- SSE-streamed reply (process_message_stream wrapping)
- PWA shell loads from /m/ (localhost; TLS deferred to Task 15)
- Asymmetric message weight (Sovereign Edge for Aetheria, dimmed Vett/Scotty)

## Not yet (queued)

- Streaming reply rendering in PWA (Task 13)
- IndexedDB outbox + service-worker retry (Task 14)
- TLS via Tailscale Funnel (Task 15)
- deliberate_share + outbound queue (Task 16+)
- Real push (Phase 4, Spark-gated)
- Read receipts surfacing to agent (Task 21)

## Architecture posture preserved

- Routes call `process_message_stream` — they do NOT write to
  conversations DB directly. Spec §4.1 honored.
- Per-thread agent binding immutable. Spec §4.2 honored.
- Aetheria's design contract intact in style.css.
- PWA shell minimal — no framework, no component library, vanilla JS.

## Known issue discovered during smoke

The SSE route in `soveryn/app/routes/messenger.py` calls `flask.jsonify`
inside its `_stream()` generator. When the generator runs after Flask
has torn down the request context (e.g. Werkzeug `test_client` buffered
mode, and likely production WSGI streaming under some servers), this
raises `RuntimeError: Working outside of application context`. The
e2e smoke sidesteps it by yielding zero events from the fake loop.
Fix is one line — wrap with `flask.stream_with_context` or swap
`jsonify` for `json.dumps`. Surface in Task 13 since that task already
edits the SSE seam end-to-end.

## Where Codex picks up

Codex's Direct Line PWA spec (2026-06-11) overlaps this work. The
substrate (auth, outbox, streaming) is now implemented in vnext under
`soveryn/app/messenger/` + `soveryn/platform/web/pwa/`. Codex's spec
revisions should target the integration seam (spec §6, the message
envelope shapes in `soveryn/app/messenger/envelope.py`) — these are
locked code-of-record now.

## Next session resumes at Task 13

Tasks 13-15 close Phase 2 (PWA polish + TLS).
Tasks 16-22 implement Phase 3 (deliberate_share + outbound queue).
