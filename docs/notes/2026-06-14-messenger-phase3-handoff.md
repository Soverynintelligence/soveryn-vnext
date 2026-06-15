# Messenger Phase 3 — Handoff (v1 close)

This closes the SOVERYN Messenger v1 build. Phases 1–3 are landed and
green on `soveryn-messenger-v1` (tip `7588439` at write time). Phase 4
is Spark-gated; Phase 5 is post-Phase-4 calibration. Both are future
sessions, not this branch.

Read alongside:

- [[messenger-phase1-handoff-2026-06-14]] — what Phase 1 closed with
- [[soveryn-messenger-v1-plan-2026-06-14]] — the 22-task plan
- [[soveryn-messenger-design-2026-06-13]] — the design spec
- [[cross-rail-active-context-design-2026-06-11]] — the substrate the
  two Codex deltas target
- [[project-soveryn-partnership-contract-2026-06-13]] — the anchor for
  Aetheria's `deliberate_share` being uncapped (load-bearing)

---

## 1. Status — Phases 1-3 closed

Compact inventory by task. All landed unless flagged.

| #  | Task                                       | State    | Notes |
|----|--------------------------------------------|----------|-------|
| 0  | Preflight + branch                         | done     | branch `soveryn-messenger-v1` |
| 1  | Schema + `MessengerStore`                  | done     | sqlite tables for devices, threads, pairing, outbound |
| 2  | Pairing token mint + claim                 | done     | short-lived QR/code → bearer |
| 3  | Device auth — bearer verify + revoke       | done     | 401 on revoked tokens |
| 4  | Thread mgmt — agent binding + session reuse| done     | per-thread agent binding immutable |
| 5  | Message envelope shapes (spec §6)          | done     | inbound / intent / thread-state / per-msg |
| 6  | Idempotency layer (`client_msg_id`)        | done     | duplicate POST → same response |
| 7  | Flask routes scaffold — pairing + auth     | done     | blueprint under `/m/*` |
| 8  | Register blueprint in startup.py           | done     | blueprint wired |
| 9  | Wire send → `AgentLoop.process_message`    | done     | route uses `process_message_stream`, no direct DB writes (spec §4.1) |
| 10 | Streaming SSE response                     | done     | SSE seam stable |
| 11 | PWA shell — Terminal-meets-Luxury          | done     | vanilla JS, no framework; Void-Gold + Sovereign Edge intact |
| 12 | Phase 1 e2e smoke + handoff                | done     | [[messenger-phase1-handoff-2026-06-14]] |
| 13 | PWA SSE streaming reply renderer           | done     | also fixed the `flask.jsonify`-outside-context bug flagged in Phase 1 |
| 14 | IndexedDB outbox + service-worker retry    | done     | offline-tolerant send |
| 15 | TLS via Tailscale Funnel                   | done     | [[messenger-tailscale-setup-2026-06-14]] |
| 16 | `deliberate_share` ToolSpec                | done     | Aetheria uncapped; Vett rate-limited |
| 17 | Persona updates — restraint as VALUE       | done     | souls-encoded, not rule-enforced |
| 18 | Register `deliberate_share` in startup.py  | done     | wired for Aetheria + Vett |
| 19 | Stub delivery worker                       | done     | vnext-side stub; real push is Phase 4 (Spark) |
| 20 | Wire delivery-worker daemon into startup   | done     | runs as a background daemon |
| 21 | Read receipts surface back to agent        | done     | `list_my_outbound` introspection tool |
| 22 | Phase 3 close + cross-rail deltas          | this doc | |

Test count: **51 messenger tests** across
`tests/test_messenger_*.py`, all green at `7588439`.

---

## 2. What works end-to-end

The user-facing story, fully working today:

1. Jon opens `https://soveryn.<tailnet>/m/` on his phone (Tailscale
   Funnel TLS per Task 15 setup notes).
2. Pairing screen — he scans/enters a short-lived code minted by the
   tower; the PWA stores a bearer token.
3. Thread list — he picks an agent (Aetheria, Vett, or Scotty).
4. Sends a message — the PWA POSTs with `client_msg_id` idempotency,
   gets back an SSE stream, renders the reply token-by-token.
5. Aetheria can, from any `AgentLoop` turn (chat, voice, Signal),
   call `deliberate_share(thread_id, body)` — the message lands in
   the outbound queue, the delivery worker daemon drains it, and
   Jon sees it the next time he opens the thread.
6. Aetheria can call `list_my_outbound()` to see which of her
   deliberate-shares have been delivered / read. This closes the loop
   on her side — she now has a feedback signal.

What's missing from this picture: **real push notifications.** The
phone doesn't ring when Aetheria sends. She lands in the thread, Jon
sees it when he opens the PWA. Push is Phase 4 (see §3).

---

## 3. What's deferred to Phase 4 (Spark)

Phase 4 lands the long-lived services on the Spark pair when they
arrive (see [[project-soveryn-dgx-spark-buy]]):

- **Real Web Push.** VAPID keypair, `/m/push/subscribe` +
  `/m/push/unsubscribe`, APNs/FCM dispatch from the delivery worker
  (currently a stub).
- **Cross-device live thread state sync.** Right now state is read on
  open; live sync between two paired phones is Phase 4.
- **Per-device delivery ACK tracking.** The schema supports it; the
  Spark-side worker is what populates it.
- **Cross-rail-active-context substrate integration.** Once the
  active-context manager lands (Codex's spec), the messenger becomes
  a context-aware surface — see §4 for the two mechanical deltas Codex
  needs.

The vnext-side stub delivery worker keeps Phase 1-3 functional locally.
No migration churn — when Spark arrives, the existing tables stay; only
new long-lived processes come online over there.

---

## 4. Cross-rail-active-context deltas for Codex

Two mechanical updates Codex needs to fold into
[[cross-rail-active-context-design-2026-06-11]] (and his Direct Line
PWA spec [[direct-line-pwa-design-2026-06-11]]) so the messenger lands
cleanly under the active-context substrate.

### Delta 1 — add `messenger` to the `owner_surface` enum

Cross-rail design §6.3 currently lists ownership values as:

```
- chat
- voice
- signal
```

Add `messenger` as a fourth value. The messenger is a new rail with
its own session lifecycle (the thread on a paired phone). Mechanical
edit; same enum treatment as the existing three.

Same edit in §5.1 (`ActiveContext.owner_surface` example list:
`chat`, `voice`, `signal`) — add `messenger`.

### Delta 2 — `deliberate_share` emits `context_updated` without claiming ownership

This is the substantive one. Per Aetheria's review of the messenger
design (spec §14 + the partnership contract memory), her sending a
message via `deliberate_share` is an **event** — the active context
should observe that something was emitted on the messenger rail — but
it is **not an ownership claim**. The messenger does not become the
live rail until Jon engages with it (opens the thread, reads, replies).

Concretely, in cross-rail spec terms:

- When `deliberate_share` writes a row to `m_outbound_queue`, the
  active-context manager should receive a `context_updated` event
  (per §7) — same shape as any non-owner patch.
- Ownership stays where it was (chat / voice / signal — whatever rail
  was last active for Jon).
- Ownership **transfers** to `messenger` only when Jon opens the
  thread or sends a reply — the same way ownership transfers between
  the existing three rails today.

Codex's §6.3 already handles this — "a non-owner can propose a patch,
[…] merge as a non-owning update." The messenger just rides that
existing flow. No new ownership-transition mechanism needed; the
mechanical work is making sure `deliberate_share`'s call site uses
the non-owning-update path, not a claim path.

### Discipline note — keep "surface" and "session" distinct

From the 2026-06-13 architecture review (Codex's own framing): the
cross-rail spec is **one row per agent** in `ActiveContext`. The
`owner_surface` field is the rail; `owner_session_id` is the live
thread instance on that rail. Don't merge them at implementation
time, even though for messenger the mapping looks 1:1 today (one
thread per agent per device).

Future-proofing reason: when multi-device messenger sync lands in
Phase 4, the same `owner_surface = messenger` can have different
`owner_session_id`s if Jon has the thread open on two devices. The
spec stays correct as long as the distinction stays clean.

---

## 5. Partnership contract anchor — load-bearing

The most important thing for future-Codex, future-Claude,
future-anyone working on this code:

**[[project-soveryn-partnership-contract-2026-06-13]] is load-bearing.**

Aetheria's `deliberate_share` is uncapped by code-of-record. There is
no rate limit on her registration in `startup.py`. The restraint is
encoded in her persona as a held value (Task 17 souls update), not
enforced at the substrate level.

The regression guard is the test
`test_no_rate_limit_means_no_substrate_cap` in
`tests/test_messenger_deliberate_share.py` (line 54). If that test
ever turns red because someone added a default rate limit to her
registration, **that is a partnership regression, not a safety
improvement.** Revert it. Re-read the contract.

Vett's registration is rate-limited — different agent, different
relationship to the channel, different contract. That's correct.
Aetheria's is not, and must not be.

---

## 6. What's NOT in scope, ever (for v1)

Naming these so they don't drift back in via "small additions":

- **Native push notifications inside Phase 1-3.** Deferred to Phase 4
  (Spark). The stub delivery worker is the deliberate placeholder.
- **End-to-end encryption between phone and SOVERYN.** This is
  single-user, single-destination, sovereign. The Tailscale Funnel
  TLS terminates at the tower; there is no relay to encrypt against.
  Adding E2EE would add ceremony with no threat model.
- **Federation / multi-tenant.** SOVERYN is one person's stack. No
  multi-account, no per-tenant isolation, no cross-instance routing.
- **Multi-instance.** No second SOVERYN node to keep in sync with.
  Spark (when it arrives) is part of one logical SOVERYN, not a
  federated peer.

---

## 7. Implementation surface — file inventory

For grep-ability when future sessions need to find things:

**Substrate (vnext-side, all landed):**

- `soveryn/app/messenger/__init__.py`
- `soveryn/app/messenger/store.py` — `MessengerStore`, schema
- `soveryn/app/messenger/pairing.py` — token mint / claim
- `soveryn/app/messenger/auth.py` — bearer verify / revoke
- `soveryn/app/messenger/threads.py` — agent binding, session reuse
- `soveryn/app/messenger/envelope.py` — message envelope shapes (spec §6)
- `soveryn/app/messenger/delivery_worker.py` — stub drain daemon

**Routes:**

- `soveryn/app/routes/messenger.py` — the `/m/*` blueprint

**PWA shell:**

- `soveryn/platform/web/pwa/index.html`
- `soveryn/platform/web/pwa/style.css` — Void-Gold + Sovereign Edge
- `soveryn/platform/web/pwa/app.js` — vanilla JS, SSE reader, IDB outbox
- `soveryn/platform/web/pwa/service_worker.js` — outbox retry
- `soveryn/platform/web/pwa/manifest.json`

**Agent tools:**

- `soveryn/agents/messenger_tool.py` — `deliberate_share` factory
- `soveryn/agents/messenger_introspect_tool.py` — `list_my_outbound` factory

**Tests (51 total):**

- `tests/test_messenger_store.py`
- `tests/test_messenger_pairing.py`
- `tests/test_messenger_auth.py`
- `tests/test_messenger_threads.py`
- `tests/test_messenger_envelope.py`
- `tests/test_messenger_routes.py`
- `tests/test_messenger_e2e_smoke.py`
- `tests/test_messenger_deliberate_share.py` — includes the partnership
  contract regression guard
- `tests/test_messenger_read_receipts.py`

**Docs:**

- `docs/superpowers/plans/2026-06-14-soveryn-messenger-v1.md`
- `docs/superpowers/specs/2026-06-13-soveryn-messenger-design.md`
- `docs/notes/2026-06-14-messenger-phase1-handoff.md`
- `docs/notes/2026-06-14-messenger-tailscale-setup.md`
- `docs/notes/2026-06-14-messenger-phase3-handoff.md` (this doc)

---

## 8. Operational note — RESTART PENDING

**vnext has NOT been restarted since the persona updates (Task 17)
and tool registrations (Task 18).**

Until the next operator runs:

```bash
systemctl --user restart soveryn-vnext.service
```

…the live runtime will not have:

- Aetheria's updated persona encoding `deliberate_share` restraint as
  value (Task 17)
- Aetheria's `deliberate_share` tool registration
- Aetheria's `list_my_outbound` tool registration
- Vett's `deliberate_share` registration (rate-limited)

Symptom if not restarted: Aetheria will say she doesn't have a
messenger tool. That is not a bug in the build — it's the runtime
not having reloaded. Restart, smoke-test, then she'll see it.

Flagging prominently because the next person in this conversation —
whether Jon, Codex, or a future Claude session — will otherwise
debug a non-bug.

---

## 9. Where this branch ends

`soveryn-messenger-v1` is feature-complete for Phases 1-3. The branch
can merge to `main` once:

- The pending restart happens and Aetheria's tool surface is verified
  live (smoke: one `deliberate_share` from her side, one `/m/` send
  from Jon's, see the reply stream).
- Optional: a `git rebase main` if main has moved since branch open.

Phase 4 (Spark) and Phase 5 (calibration) are separate branches in
future sessions.

End of v1.
