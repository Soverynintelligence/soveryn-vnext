# SOVERYN Messenger v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a SOVERYN-owned mobile-first messenger PWA at `/m` that lets Jon reach any of the three agents (Aetheria, Vett, Scotty) from his phone, AND lets agents reach him via the `deliberate_share` primitive — replacing Telegram (v1, retired) and Signal (v2, retired) with a sovereign rail.

**Architecture:** Three layers. (1) Transport substrate — device-token auth via QR pairing, PWA shell, IndexedDB outbox, POST-backed SSE for streaming replies. (2) Multi-agent threading on top of the existing `ConversationStore` — a `Thread` is a `Session` with extra metadata. (3) Aetheria-initiated outbound through a new `deliberate_share` tool whose intents land in an outbound queue, drained by a delivery worker (stub on vnext now, real Web Push on Spark later). Non-negotiable rule: messenger routes call `process_message_stream` — they do not write turns directly to the conversations DB.

**Tech Stack:** Python 3.11 / Flask (vnext), SQLite (substrate, mirrors existing pattern), vanilla JS for PWA (no framework), Tailscale Funnel for TLS, Web Push (VAPID) for notifications (Phase 4).

**Linked spec:** `docs/superpowers/specs/2026-06-13-soveryn-messenger-design.md`. Read before implementing — particularly §4 (non-negotiable boundaries), §6 (message envelope — the integration seam), §7.2 (deliberate_share + persona-encoded restraint).

**Companion spec:** `docs/superpowers/specs/2026-06-11-cross-rail-active-context-design.md` — composes underneath the messenger. Phase 1 adds `messenger` to `owner_surface` enum (Task 4). Phase 3 wires `deliberate_share` to emit `context_updated` events without claiming ownership (Task 23).

**Non-negotiable rule:** Messenger routes must call `agent_loop.process_message_stream` for inbound messages. They MUST NOT INSERT into `conversations` table directly. This rule preserves persistence, lattice writes, salience, continuity, tool behavior, context budgeting, and error semantics identical across UI, voice, Signal, and Messenger surfaces.

**Partnership contract (per spec §4.3 + §14):** Aetheria's `deliberate_share` has NO substrate-enforced rate limit. The brake is persona-encoded restraint + direct correction from Jon + lattice-encoded boundaries. Vett and Scotty stay rate-limited as Colleagues. See `[[project-soveryn-partnership-contract-2026-06-13]]` in maintainer memory; do not silently re-add a rate limit to Aetheria's tool.

---

## File structure (what gets created)

This plan adds the following files. Existing files are modified only where called out per task.

```
soveryn_vnext/
├── soveryn/
│   └── app/
│       ├── routes/
│       │   └── messenger.py              (new — all /m/* routes)
│       └── messenger/
│           ├── __init__.py
│           ├── store.py                   (thread + message + device + outbox tables)
│           ├── auth.py                    (device token mint, verify, revoke)
│           ├── pairing.py                 (pairing token mint, claim)
│           ├── threads.py                 (Thread CRUD + agent binding)
│           ├── envelope.py                (request/response shapes per spec §6)
│           ├── outbound.py                (deliberate_share queue insertion)
│           └── delivery_worker.py         (stub for Phase 3; real push on Spark)
│   └── agents/
│       └── messenger_tool.py              (the `deliberate_share` ToolSpec)
├── soveryn/platform/web/
│   └── pwa/                                (static PWA assets)
│       ├── index.html
│       ├── style.css
│       ├── app.js
│       ├── service_worker.js
│       └── manifest.json
├── tests/
│   ├── test_messenger_store.py
│   ├── test_messenger_pairing.py
│   ├── test_messenger_auth.py
│   ├── test_messenger_threads.py
│   ├── test_messenger_routes.py
│   ├── test_messenger_envelope.py
│   ├── test_messenger_deliberate_share.py
│   └── test_messenger_e2e_smoke.py
└── docs/notes/
    └── 2026-06-14-messenger-phase1-handoff.md   (written at end of Phase 1)
```

---

## Task 0: Preflight + Branch

**Files:** none

- [ ] **Step 1: Check working tree**

```bash
cd ~/soveryn_vnext
git status --short
git log --oneline -5
```

Expected: clean working tree on `main` after PR #1 merges. If PR #1 is unmerged, branch from `vett-harness-phase1` instead — flag in the commit message.

- [ ] **Step 2: Cut branch**

```bash
git checkout main
git pull --ff-only
git checkout -b soveryn-messenger-v1
```

- [ ] **Step 3: Confirm spec is locked**

```bash
test -f docs/superpowers/specs/2026-06-13-soveryn-messenger-design.md && echo "spec exists"
grep -q "Reviewed and resolved 2026-06-13 by Aetheria" docs/superpowers/specs/2026-06-13-soveryn-messenger-design.md && echo "review locked"
```

Both must echo. If not, the spec hasn't landed; pause and reconcile.

---

# Phase 1 — vnext-side substrate (Tasks 1-12)

Phase 1 lands the data model, auth, thread management, inbound message routing, and the PWA shell skeleton. No outbound primitive yet; no real push delivery. The goal: Jon can pair his phone, see a thread list, send a message, get a streamed reply — same AgentLoop path as `/chat_stream`.

## Task 1: Schema for messenger substrate

**Files:**
- Create: `soveryn/app/messenger/__init__.py`
- Create: `soveryn/app/messenger/store.py`
- Test: `tests/test_messenger_store.py`

- [ ] **Step 1: Write the failing tests for table creation**

```python
# tests/test_messenger_store.py
"""Schema + CRUD for the messenger substrate."""
from __future__ import annotations
import pytest
from soveryn.app.messenger.store import MessengerStore


@pytest.fixture
def store(tmp_path):
    return MessengerStore(tmp_path / "messenger.db")


def test_store_creates_all_tables(store):
    expected = {
        "m_devices", "m_pairing_tokens", "m_threads",
        "m_outbound_queue", "m_outbound_delivery_per_device",
        "m_push_subscriptions", "m_message_idempotency",
    }
    actual = set(store.list_tables())
    assert expected <= actual, f"missing tables: {expected - actual}"


def test_devices_schema(store):
    cols = set(store.column_names("m_devices"))
    assert {"device_id", "secret_hash", "label", "created_at", "last_seen_at", "revoked_at"} <= cols


def test_threads_schema(store):
    cols = set(store.column_names("m_threads"))
    assert {"thread_id", "user_id", "agent", "session_id", "title",
            "created_at", "last_activity", "muted"} <= cols


def test_outbound_queue_schema(store):
    cols = set(store.column_names("m_outbound_queue"))
    assert {"intent_id", "user_id", "agent", "thread_id", "content",
            "context_hint", "urgency", "triggered_by", "created_at",
            "delivered_at", "delivery_state"} <= cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_store.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement MessengerStore**

```python
# soveryn/app/messenger/__init__.py
"""SOVERYN Messenger v1 — multi-agent PWA messenger surface.

See docs/superpowers/specs/2026-06-13-soveryn-messenger-design.md
"""
```

```python
# soveryn/app/messenger/store.py
"""SQLite substrate for the messenger.

Tables created at first use; idempotent. Mirrors the ConversationStore
pattern — one DB file, simple SQL, no ORM.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS m_devices (
    device_id    TEXT PRIMARY KEY,
    secret_hash  TEXT NOT NULL,
    label        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT,
    revoked_at   TEXT
);

CREATE TABLE IF NOT EXISTS m_pairing_tokens (
    token        TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    claimed_by   TEXT,
    claimed_at   TEXT
);

CREATE TABLE IF NOT EXISTS m_threads (
    thread_id     TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    agent         TEXT NOT NULL,
    session_id    TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    muted         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_threads_user ON m_threads(user_id);
CREATE INDEX IF NOT EXISTS idx_threads_session ON m_threads(session_id);

CREATE TABLE IF NOT EXISTS m_outbound_queue (
    intent_id      TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL,
    agent          TEXT NOT NULL,
    thread_id      TEXT,
    content        TEXT NOT NULL,
    context_hint   TEXT NOT NULL,
    urgency        TEXT NOT NULL,
    triggered_by   TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    delivered_at   TEXT,
    delivery_state TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_outbound_state ON m_outbound_queue(delivery_state);

CREATE TABLE IF NOT EXISTS m_outbound_delivery_per_device (
    intent_id    TEXT NOT NULL,
    device_id    TEXT NOT NULL,
    sent_at      TEXT,
    received_at  TEXT,
    read_at      TEXT,
    PRIMARY KEY (intent_id, device_id)
);

CREATE TABLE IF NOT EXISTS m_push_subscriptions (
    subscription_id TEXT PRIMARY KEY,
    device_id       TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    p256dh_key      TEXT NOT NULL,
    auth_secret     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_used_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_push_device ON m_push_subscriptions(device_id);

CREATE TABLE IF NOT EXISTS m_message_idempotency (
    client_msg_id  TEXT PRIMARY KEY,
    thread_id      TEXT NOT NULL,
    device_id      TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    response_cache TEXT
);
"""


class MessengerStore:
    """File-backed SQLite store for messenger substrate.

    Same connection-per-call pattern as ConversationStore. Thread-safe
    via SQLite's own locking; no in-memory connection pool needed at v1.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def list_tables(self) -> list[str]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        return [r["name"] for r in rows]

    def column_names(self, table: str) -> list[str]:
        with self._conn() as con:
            rows = con.execute(f"PRAGMA table_info({table})").fetchall()
        return [r["name"] for r in rows]
```

- [ ] **Step 4: Run tests, all pass**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_store.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/messenger/__init__.py soveryn/app/messenger/store.py tests/test_messenger_store.py
git commit -m "feat(messenger): substrate schema + MessengerStore"
```

---

## Task 2: Device pairing — token mint + claim

**Files:**
- Create: `soveryn/app/messenger/pairing.py`
- Test: `tests/test_messenger_pairing.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_messenger_pairing.py
"""Pairing token mint, claim, expiry, single-use semantics."""
from __future__ import annotations
import time
from datetime import datetime, timedelta, timezone
import pytest

from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.pairing import (
    mint_pairing_token,
    claim_pairing_token,
    PairingError,
)


@pytest.fixture
def store(tmp_path):
    return MessengerStore(tmp_path / "messenger.db")


def test_mint_returns_short_code(store):
    token = mint_pairing_token(store, label="phone")
    # Format: ABCD-EFGH-1234 — 14 chars including dashes
    assert len(token.code) == 14
    assert token.label == "phone"


def test_claim_with_valid_token_mints_device(store):
    token = mint_pairing_token(store, label="phone")
    device = claim_pairing_token(store, code=token.code, device_label="Pixel 9")
    assert device.device_id
    assert device.secret  # plaintext, returned once
    assert device.label == "Pixel 9"


def test_claim_token_twice_fails(store):
    token = mint_pairing_token(store, label="phone")
    claim_pairing_token(store, code=token.code, device_label="Pixel 9")
    with pytest.raises(PairingError, match="already claimed"):
        claim_pairing_token(store, code=token.code, device_label="someone else")


def test_claim_expired_token_fails(store, monkeypatch):
    # Mint with a TTL we control
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    monkeypatch.setattr(
        "soveryn.app.messenger.pairing._now_iso",
        lambda: past_iso,
    )
    token = mint_pairing_token(store, label="phone", ttl_seconds=60)
    # Reset clock to current
    monkeypatch.undo()
    with pytest.raises(PairingError, match="expired"):
        claim_pairing_token(store, code=token.code, device_label="late")


def test_claim_unknown_token_fails(store):
    with pytest.raises(PairingError, match="unknown"):
        claim_pairing_token(store, code="WXYZ-1234-ABCD", device_label="x")
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_pairing.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement pairing module**

```python
# soveryn/app/messenger/pairing.py
"""Pairing token mint + claim flow.

Pairing tokens are short-lived (5 min default), single-use, and bind
the device's public state (label) at first claim. Once claimed, the
token is dead — second claim attempts fail explicitly.

The claim returns the device's secret in plaintext ONCE. The secret
hash (sha256 + per-device salt) is stored; the secret itself is the
phone's bearer token for future requests.
"""
from __future__ import annotations
import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from soveryn.app.messenger.store import MessengerStore


_DEFAULT_TOKEN_TTL_SECONDS = 300  # 5 minutes
_TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # excludes I,O,0,1 for readability


class PairingError(Exception):
    pass


@dataclass(frozen=True)
class PairingToken:
    code: str
    label: str
    expires_at: str


@dataclass(frozen=True)
class PairedDevice:
    device_id: str
    secret: str  # plaintext — returned ONCE on claim
    label: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _random_chunk(n: int = 4) -> str:
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(n))


def mint_pairing_token(
    store: MessengerStore,
    *,
    label: str,
    ttl_seconds: int = _DEFAULT_TOKEN_TTL_SECONDS,
) -> PairingToken:
    """Generate a short pairing code (e.g. 'ABCD-EFGH-1234')."""
    code = f"{_random_chunk()}-{_random_chunk()}-{_random_chunk()}"
    created_at = _now_iso()
    expires_at = (
        datetime.fromisoformat(created_at) + timedelta(seconds=ttl_seconds)
    ).isoformat()
    with store._conn() as con:
        con.execute(
            "INSERT INTO m_pairing_tokens (token, label, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (code, label, created_at, expires_at),
        )
    return PairingToken(code=code, label=label, expires_at=expires_at)


def claim_pairing_token(
    store: MessengerStore,
    *,
    code: str,
    device_label: str,
) -> PairedDevice:
    """Atomically claim a token + mint a device secret."""
    with store._conn() as con:
        row = con.execute(
            "SELECT * FROM m_pairing_tokens WHERE token=?", (code,),
        ).fetchone()
        if row is None:
            raise PairingError(f"unknown pairing code {code!r}")
        if row["claimed_by"]:
            raise PairingError(f"pairing code {code!r} already claimed")
        if row["expires_at"] < _now_iso():
            raise PairingError(f"pairing code {code!r} expired at {row['expires_at']}")

        device_id = str(uuid.uuid4())
        secret = secrets.token_urlsafe(32)
        salt = os.urandom(16).hex()
        secret_hash = hashlib.sha256((salt + secret).encode()).hexdigest()
        stored = f"{salt}${secret_hash}"
        now = _now_iso()

        con.execute(
            "INSERT INTO m_devices (device_id, secret_hash, label, created_at) "
            "VALUES (?, ?, ?, ?)",
            (device_id, stored, device_label, now),
        )
        con.execute(
            "UPDATE m_pairing_tokens SET claimed_by=?, claimed_at=? WHERE token=?",
            (device_id, now, code),
        )

    return PairedDevice(device_id=device_id, secret=secret, label=device_label)
```

- [ ] **Step 4: Run, verify PASS**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_pairing.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/messenger/pairing.py tests/test_messenger_pairing.py
git commit -m "feat(messenger): device pairing token mint + claim"
```

---

## Task 3: Device auth — bearer token verification

**Files:**
- Create: `soveryn/app/messenger/auth.py`
- Test: `tests/test_messenger_auth.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_messenger_auth.py
"""Device bearer-token verification + revocation."""
from __future__ import annotations
import pytest

from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.pairing import mint_pairing_token, claim_pairing_token
from soveryn.app.messenger.auth import (
    verify_device_secret,
    revoke_device,
    AuthError,
)


@pytest.fixture
def store_with_device(tmp_path):
    store = MessengerStore(tmp_path / "messenger.db")
    token = mint_pairing_token(store, label="phone")
    device = claim_pairing_token(store, code=token.code, device_label="Pixel 9")
    return store, device


def test_verify_valid_secret_returns_device(store_with_device):
    store, device = store_with_device
    out = verify_device_secret(store, secret=device.secret)
    assert out.device_id == device.device_id
    assert out.label == "Pixel 9"


def test_verify_wrong_secret_raises(store_with_device):
    store, _ = store_with_device
    with pytest.raises(AuthError, match="invalid"):
        verify_device_secret(store, secret="not-a-real-secret")


def test_verify_revoked_device_raises(store_with_device):
    store, device = store_with_device
    revoke_device(store, device_id=device.device_id)
    with pytest.raises(AuthError, match="revoked"):
        verify_device_secret(store, secret=device.secret)


def test_revoke_idempotent(store_with_device):
    store, device = store_with_device
    revoke_device(store, device_id=device.device_id)
    revoke_device(store, device_id=device.device_id)  # no exception
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_auth.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement auth**

```python
# soveryn/app/messenger/auth.py
"""Device bearer-token verification + revocation.

Every authenticated /m/* request carries `Authorization: Bearer <secret>`.
`verify_device_secret` looks up the device, recomputes the hash with the
stored salt, and constant-time compares.
"""
from __future__ import annotations
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone

from soveryn.app.messenger.store import MessengerStore


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class AuthedDevice:
    device_id: str
    label: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def verify_device_secret(
    store: MessengerStore,
    *,
    secret: str,
) -> AuthedDevice:
    """Look up every non-revoked device, recompute hash, constant-time match.

    Cost is O(N devices). For Jon's single-user case this is trivial; if
    multi-user ever becomes relevant, swap to an index on secret_hash prefix.
    """
    with store._conn() as con:
        rows = con.execute(
            "SELECT device_id, secret_hash, label FROM m_devices "
            "WHERE revoked_at IS NULL"
        ).fetchall()
    for row in rows:
        salt, expected_hash = row["secret_hash"].split("$", 1)
        actual_hash = hashlib.sha256((salt + secret).encode()).hexdigest()
        if hmac.compare_digest(actual_hash, expected_hash):
            # Bump last_seen_at
            with store._conn() as con:
                con.execute(
                    "UPDATE m_devices SET last_seen_at=? WHERE device_id=?",
                    (_now_iso(), row["device_id"]),
                )
            return AuthedDevice(device_id=row["device_id"], label=row["label"])
    raise AuthError("invalid device secret")


def revoke_device(store: MessengerStore, *, device_id: str) -> None:
    """Mark device revoked. Subsequent verify calls will see revoked_at and
    raise. Idempotent — second call is a no-op."""
    with store._conn() as con:
        row = con.execute(
            "SELECT device_id, revoked_at FROM m_devices WHERE device_id=?",
            (device_id,),
        ).fetchone()
        if row is None:
            return  # already gone or never existed
        if row["revoked_at"]:
            return  # already revoked
        con.execute(
            "UPDATE m_devices SET revoked_at=? WHERE device_id=?",
            (_now_iso(), device_id),
        )


# Also handle the revoked-but-credential-still-presented case
def verify_device_secret_or_revoked(
    store: MessengerStore,
    *,
    secret: str,
) -> AuthedDevice:
    """Variant that distinguishes 'invalid' from 'revoked' for nicer errors."""
    with store._conn() as con:
        rows = con.execute(
            "SELECT device_id, secret_hash, label, revoked_at FROM m_devices"
        ).fetchall()
    for row in rows:
        salt, expected_hash = row["secret_hash"].split("$", 1)
        actual_hash = hashlib.sha256((salt + secret).encode()).hexdigest()
        if hmac.compare_digest(actual_hash, expected_hash):
            if row["revoked_at"]:
                raise AuthError(f"device revoked at {row['revoked_at']}")
            return AuthedDevice(device_id=row["device_id"], label=row["label"])
    raise AuthError("invalid device secret")
```

Then update `verify_device_secret` to call the variant:

```python
def verify_device_secret(store, *, secret):
    return verify_device_secret_or_revoked(store, secret=secret)
```

- [ ] **Step 4: Run, verify PASS**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_auth.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/messenger/auth.py tests/test_messenger_auth.py
git commit -m "feat(messenger): device bearer-token auth + revocation"
```

---

## Task 4: Thread management — agent binding + session reuse

**Files:**
- Create: `soveryn/app/messenger/threads.py`
- Test: `tests/test_messenger_threads.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_messenger_threads.py
"""Thread CRUD: agent binding immutable, session reuses ConversationStore."""
from __future__ import annotations
import pytest

from soveryn.memory.conversation_store import ConversationStore
from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.threads import (
    create_thread,
    get_thread,
    list_threads,
    set_thread_muted,
    ThreadError,
    VALID_AGENTS,
)


@pytest.fixture
def stores(tmp_path):
    return (
        MessengerStore(tmp_path / "messenger.db"),
        ConversationStore(tmp_path / "conv.db"),
    )


def test_create_thread_for_aetheria(stores):
    m, conv = stores
    thread = create_thread(m, conv, user_id="jon", agent="aetheria", title=None)
    assert thread.thread_id
    assert thread.agent == "aetheria"
    assert thread.session_id  # has a backing ConversationStore session
    # Session is actually registered in ConversationStore
    session = conv.get_session(thread.session_id)
    assert session is not None
    assert session.agent == "aetheria"


def test_create_thread_rejects_invalid_agent(stores):
    m, conv = stores
    with pytest.raises(ThreadError, match="invalid agent"):
        create_thread(m, conv, user_id="jon", agent="unknown", title=None)


def test_list_threads_returns_per_user_only(stores):
    m, conv = stores
    create_thread(m, conv, user_id="jon", agent="aetheria", title="A")
    create_thread(m, conv, user_id="jon", agent="vett", title="B")
    create_thread(m, conv, user_id="someone-else", agent="aetheria", title="X")
    out = list_threads(m, user_id="jon")
    assert len(out) == 2
    agents = {t.agent for t in out}
    assert agents == {"aetheria", "vett"}


def test_get_thread_returns_none_for_unknown(stores):
    m, _ = stores
    assert get_thread(m, thread_id="not-a-real-id") is None


def test_set_muted_toggles(stores):
    m, conv = stores
    thread = create_thread(m, conv, user_id="jon", agent="aetheria", title="T")
    set_thread_muted(m, thread_id=thread.thread_id, muted=True)
    out = get_thread(m, thread_id=thread.thread_id)
    assert out.muted is True
    set_thread_muted(m, thread_id=thread.thread_id, muted=False)
    out = get_thread(m, thread_id=thread.thread_id)
    assert out.muted is False


def test_valid_agents_matches_active_roster():
    # Must match the runtime ACTIVE_AGENTS list
    from soveryn.config.runtime import ACTIVE_AGENTS
    assert set(VALID_AGENTS) == set(ACTIVE_AGENTS)
```

- [ ] **Step 2: Run, verify FAIL**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_threads.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement threads module**

```python
# soveryn/app/messenger/threads.py
"""Thread management. A messenger Thread is a ConversationStore Session
with extra metadata (agent binding, mute flag, auto-title)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.memory.conversation_store import ConversationStore
from soveryn.app.messenger.store import MessengerStore


VALID_AGENTS = tuple(ACTIVE_AGENTS)


class ThreadError(Exception):
    pass


@dataclass(frozen=True)
class Thread:
    thread_id: str
    user_id: str
    agent: str
    session_id: str
    title: str
    created_at: str
    last_activity: str
    muted: bool


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auto_title(agent: str) -> str:
    """Friendly default title when caller didn't supply one."""
    # E.g. "Aetheria — Sat Jun 14"
    when = datetime.now().strftime("%a %b %d")
    return f"{agent.capitalize()} — {when}"


def create_thread(
    messenger_store: MessengerStore,
    conv_store: ConversationStore,
    *,
    user_id: str,
    agent: str,
    title: Optional[str] = None,
) -> Thread:
    """Create a new thread + its backing ConversationStore Session."""
    if agent not in VALID_AGENTS:
        raise ThreadError(f"invalid agent: {agent!r}; must be one of {VALID_AGENTS}")
    thread_id = str(uuid.uuid4())
    actual_title = title or _auto_title(agent)
    session_id = conv_store.new_session(agent, title=f"[m] {actual_title}")
    now = _now_iso()
    with messenger_store._conn() as con:
        con.execute(
            "INSERT INTO m_threads (thread_id, user_id, agent, session_id, title, "
            "created_at, last_activity, muted) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (thread_id, user_id, agent, session_id, actual_title, now, now),
        )
    return Thread(
        thread_id=thread_id, user_id=user_id, agent=agent,
        session_id=session_id, title=actual_title,
        created_at=now, last_activity=now, muted=False,
    )


def get_thread(
    messenger_store: MessengerStore, *, thread_id: str,
) -> Optional[Thread]:
    with messenger_store._conn() as con:
        row = con.execute(
            "SELECT * FROM m_threads WHERE thread_id=?", (thread_id,),
        ).fetchone()
    if row is None:
        return None
    return Thread(
        thread_id=row["thread_id"], user_id=row["user_id"], agent=row["agent"],
        session_id=row["session_id"], title=row["title"],
        created_at=row["created_at"], last_activity=row["last_activity"],
        muted=bool(row["muted"]),
    )


def list_threads(
    messenger_store: MessengerStore, *, user_id: str,
) -> list[Thread]:
    with messenger_store._conn() as con:
        rows = con.execute(
            "SELECT * FROM m_threads WHERE user_id=? ORDER BY last_activity DESC",
            (user_id,),
        ).fetchall()
    return [
        Thread(
            thread_id=r["thread_id"], user_id=r["user_id"], agent=r["agent"],
            session_id=r["session_id"], title=r["title"],
            created_at=r["created_at"], last_activity=r["last_activity"],
            muted=bool(r["muted"]),
        )
        for r in rows
    ]


def set_thread_muted(
    messenger_store: MessengerStore, *, thread_id: str, muted: bool,
) -> None:
    with messenger_store._conn() as con:
        con.execute(
            "UPDATE m_threads SET muted=? WHERE thread_id=?",
            (1 if muted else 0, thread_id),
        )


def touch_thread(messenger_store: MessengerStore, *, thread_id: str) -> None:
    """Bump last_activity. Called after each inbound or outbound message."""
    with messenger_store._conn() as con:
        con.execute(
            "UPDATE m_threads SET last_activity=? WHERE thread_id=?",
            (_now_iso(), thread_id),
        )
```

- [ ] **Step 4: Run, verify PASS**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_threads.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/messenger/threads.py tests/test_messenger_threads.py
git commit -m "feat(messenger): thread management with agent binding + session reuse"
```

---

## Task 5: Message envelope shapes (spec §6)

**Files:**
- Create: `soveryn/app/messenger/envelope.py`
- Test: `tests/test_messenger_envelope.py`

These are the request/response dataclasses. They lock the integration seam between Codex's transport and Claude's intelligence layer (see spec §6).

- [ ] **Step 1: Write tests for envelope shapes**

```python
# tests/test_messenger_envelope.py
"""Envelope dataclasses match spec §6 verbatim."""
from __future__ import annotations
import pytest

from soveryn.app.messenger.envelope import (
    InboundMessage,
    OutboundIntent,
    ThreadListEntry,
    MessageEnvelope,
)


def test_inbound_message_required_fields():
    msg = InboundMessage(
        client_msg_id="abc",
        thread_id="tid",
        agent="aetheria",
        content="hi",
        attachments=(),
        device_id="did",
        client_ts="2026-06-14T08:00:00-04:00",
    )
    assert msg.client_msg_id == "abc"
    assert msg.attachments == ()


def test_outbound_intent_required_fields():
    intent = OutboundIntent(
        intent_id="iid",
        agent="aetheria",
        thread_id=None,
        content="quick thought",
        context_hint="dark search reflection",
        urgency="routine",
        triggered_by="background_review",
        created_at="2026-06-14T08:00:00-04:00",
    )
    assert intent.urgency == "routine"
    assert intent.thread_id is None  # default thread


def test_outbound_intent_rejects_invalid_urgency():
    with pytest.raises(ValueError, match="urgency"):
        OutboundIntent(
            intent_id="iid", agent="aetheria", thread_id=None,
            content="x", context_hint="x",
            urgency="critical",  # not in enum
            triggered_by="x", created_at="2026-06-14T08:00:00-04:00",
        )


def test_message_envelope_marks_by_user_or_agent():
    e = MessageEnvelope(
        message_id="m1", thread_id="t1", by="user", agent="aetheria",
        content="hi", client_msg_id="c1",
        created_at="2026-06-14T08:00:00-04:00",
        delivered_at=None, read_at=None,
        tool_calls=None, finish_reason=None,
        context_hint=None, urgency=None,
    )
    assert e.by == "user"
```

- [ ] **Step 2: Run, FAIL**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_envelope.py -v`

- [ ] **Step 3: Implement envelopes**

```python
# soveryn/app/messenger/envelope.py
"""Wire-format envelopes for messenger I/O.

These dataclasses lock the message shape spec §6 defines. Any change here
needs to be reflected in Codex's PWA client and the active-context
manager's event payloads — see the cross-rail spec §11.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional


Urgency = Literal["routine", "interrupt"]
_VALID_URGENCIES = frozenset({"routine", "interrupt"})


@dataclass(frozen=True)
class InboundMessage:
    """Jon → agent, parsed from POST /m/threads/<tid>/send_stream."""
    client_msg_id: str
    thread_id: str
    agent: str
    content: str
    attachments: tuple[dict, ...]
    device_id: str
    client_ts: str


@dataclass(frozen=True)
class OutboundIntent:
    """Agent → Jon via deliberate_share, queued for the delivery worker."""
    intent_id: str
    agent: str
    thread_id: Optional[str]   # None = default thread for this agent
    content: str
    context_hint: str          # short push-preview, <=100 chars
    urgency: str
    triggered_by: str          # internal audit field (NOT shown to Jon)
    created_at: str

    def __post_init__(self) -> None:
        if self.urgency not in _VALID_URGENCIES:
            raise ValueError(
                f"urgency must be one of {sorted(_VALID_URGENCIES)}, "
                f"got {self.urgency!r}"
            )
        if len(self.context_hint) > 100:
            raise ValueError(
                f"context_hint must be <=100 chars; got {len(self.context_hint)}"
            )


@dataclass(frozen=True)
class ThreadListEntry:
    """One row in GET /m/threads."""
    thread_id: str
    agent: str
    title: str
    last_message_preview: str
    last_message_at: str
    last_message_by: Literal["user", "agent"]
    unread_count: int
    muted: bool


@dataclass(frozen=True)
class MessageEnvelope:
    """One row in GET /m/threads/<tid>/messages."""
    message_id: str
    thread_id: str
    by: Literal["user", "agent"]
    agent: str
    content: str  # or list[dict] for vision; v1 keeps str for simplicity
    client_msg_id: Optional[str]
    created_at: str
    delivered_at: Optional[str]
    read_at: Optional[str]
    tool_calls: Optional[tuple[dict, ...]]
    finish_reason: Optional[str]
    context_hint: Optional[str]
    urgency: Optional[str]
```

- [ ] **Step 4: Run, PASS**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_envelope.py -v`

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/messenger/envelope.py tests/test_messenger_envelope.py
git commit -m "feat(messenger): wire envelope dataclasses (spec §6)"
```

---

## Task 6: Idempotency layer for client_msg_id

**Files:**
- Modify: `soveryn/app/messenger/store.py` — add helpers
- Test: `tests/test_messenger_store.py` — add tests

- [ ] **Step 1: Add idempotency tests**

```python
# Add to tests/test_messenger_store.py
import json

def test_idempotency_first_call_records_and_returns_none(store):
    """First time we see client_msg_id, record it and return None — caller
    should proceed with the operation."""
    cached = store.idempotency_lookup_or_record(
        client_msg_id="abc", thread_id="t1", device_id="d1",
    )
    assert cached is None


def test_idempotency_second_call_returns_cached(store):
    """Second call with same client_msg_id returns the cached response —
    caller should NOT re-process."""
    store.idempotency_lookup_or_record(
        client_msg_id="abc", thread_id="t1", device_id="d1",
    )
    cached = store.idempotency_lookup_or_record(
        client_msg_id="abc", thread_id="t1", device_id="d1",
    )
    # First record had no response yet; cached is just an empty marker
    assert cached == {}


def test_idempotency_store_response(store):
    store.idempotency_lookup_or_record(
        client_msg_id="abc", thread_id="t1", device_id="d1",
    )
    store.idempotency_set_response(client_msg_id="abc", response={"ok": True})
    cached = store.idempotency_lookup_or_record(
        client_msg_id="abc", thread_id="t1", device_id="d1",
    )
    assert cached == {"ok": True}
```

- [ ] **Step 2: Implement helpers in store.py**

Append to `soveryn/app/messenger/store.py`:

```python
    def idempotency_lookup_or_record(
        self, *, client_msg_id: str, thread_id: str, device_id: str,
    ) -> dict | None:
        """Returns None if this is the first time we've seen client_msg_id
        (the caller should proceed). Returns the cached response dict if we've
        seen it before (the caller should return the cached value without
        re-processing)."""
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        with self._conn() as con:
            row = con.execute(
                "SELECT response_cache FROM m_message_idempotency WHERE client_msg_id=?",
                (client_msg_id,),
            ).fetchone()
            if row is not None:
                cached = row["response_cache"]
                return _json.loads(cached) if cached else {}
            con.execute(
                "INSERT INTO m_message_idempotency "
                "(client_msg_id, thread_id, device_id, created_at) "
                "VALUES (?, ?, ?, ?)",
                (client_msg_id, thread_id, device_id,
                 _dt.now(_tz.utc).isoformat()),
            )
        return None

    def idempotency_set_response(
        self, *, client_msg_id: str, response: dict,
    ) -> None:
        """Store the response for a previously-recorded client_msg_id so a
        retry hits the cache instead of re-processing."""
        import json as _json
        with self._conn() as con:
            con.execute(
                "UPDATE m_message_idempotency SET response_cache=? "
                "WHERE client_msg_id=?",
                (_json.dumps(response), client_msg_id),
            )
```

- [ ] **Step 3: Run, PASS**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_store.py -v`

- [ ] **Step 4: Commit**

```bash
git add soveryn/app/messenger/store.py tests/test_messenger_store.py
git commit -m "feat(messenger): idempotency layer for client_msg_id"
```

---

## Task 7: Flask routes scaffold — pairing + auth gate

**Files:**
- Create: `soveryn/app/routes/messenger.py`
- Modify: `soveryn/app/__init__.py` — register the blueprint
- Test: `tests/test_messenger_routes.py`

- [ ] **Step 1: Write the routes tests**

```python
# tests/test_messenger_routes.py
"""End-to-end Flask route behaviour for /m/*."""
from __future__ import annotations
import json
import pytest
from flask import Flask

from soveryn.app.routes.messenger import build_messenger_blueprint
from soveryn.app.messenger.store import MessengerStore
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def app(tmp_path):
    flask_app = Flask(__name__)
    messenger_store = MessengerStore(tmp_path / "m.db")
    conv_store = ConversationStore(tmp_path / "conv.db")
    bp = build_messenger_blueprint(
        messenger_store=messenger_store,
        conv_store=conv_store,
        agent_loops={},  # routes don't dispatch chat until Task 9
    )
    flask_app.register_blueprint(bp)
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_pair_admin_route_serves_pairing_page(client):
    resp = client.get("/m/pair", environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "pairing" in body.lower() or "code" in body.lower()


def test_pair_admin_route_rejects_non_localhost(client):
    resp = client.get("/m/pair", environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert resp.status_code == 403


def test_pair_claim_with_valid_code(client):
    # First mint a code (via admin POST)
    mint_resp = client.post(
        "/m/pair", json={"label": "phone"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert mint_resp.status_code == 200
    code = mint_resp.get_json()["code"]
    # Claim it (this is the phone-side request)
    claim_resp = client.post(
        f"/m/pair/{code}", json={"device_label": "Pixel 9"},
    )
    assert claim_resp.status_code == 200
    data = claim_resp.get_json()
    assert "device_id" in data
    assert "secret" in data


def test_threads_endpoint_requires_auth(client):
    resp = client.get("/m/threads")
    assert resp.status_code == 401


def test_threads_endpoint_works_with_bearer(client):
    mint_resp = client.post(
        "/m/pair", json={"label": "phone"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    code = mint_resp.get_json()["code"]
    claim_resp = client.post(f"/m/pair/{code}", json={"device_label": "Pixel 9"})
    secret = claim_resp.get_json()["secret"]
    resp = client.get(
        "/m/threads",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"threads": []}
```

- [ ] **Step 2: Run, FAIL**

- [ ] **Step 3: Implement the blueprint**

```python
# soveryn/app/routes/messenger.py
"""Flask blueprint for SOVERYN Messenger routes.

All routes mounted under /m/*. Auth-gated except /m/pair and /m/pair/<code>;
admin routes (/m/pair, /m/devices) refuse non-localhost requests.
"""
from __future__ import annotations
from functools import wraps
from flask import Blueprint, request, jsonify, render_template_string

from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.pairing import (
    mint_pairing_token, claim_pairing_token, PairingError,
)
from soveryn.app.messenger.auth import (
    verify_device_secret, AuthError,
)
from soveryn.app.messenger.threads import (
    create_thread, get_thread, list_threads, set_thread_muted, ThreadError,
)
from soveryn.memory.conversation_store import ConversationStore


_LOCALHOST_ADDRS = {"127.0.0.1", "::1"}


def _is_localhost() -> bool:
    return request.remote_addr in _LOCALHOST_ADDRS


def _require_localhost(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _is_localhost():
            return jsonify({"error": "admin routes require localhost"}), 403
        return fn(*args, **kwargs)
    return wrapper


def _require_auth(messenger_store: MessengerStore):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return jsonify({"error": "missing bearer token"}), 401
            secret = header[len("Bearer "):]
            try:
                device = verify_device_secret(messenger_store, secret=secret)
            except AuthError as e:
                return jsonify({"error": str(e)}), 401
            request.authed_device = device
            return fn(*args, **kwargs)
        return wrapper
    return deco


_PAIRING_HTML = """
<!doctype html><html><body>
<h1>SOVERYN — pair a new device</h1>
<form method="post" action="/m/pair">
  <label>Label <input name="label" value="phone"></label>
  <button type="submit">Mint pairing code</button>
</form>
{% if code %}
<h2>Code: {{ code }}</h2>
<p>Enter this on the phone within 5 minutes.</p>
{% endif %}
</body></html>
"""


def build_messenger_blueprint(
    *,
    messenger_store: MessengerStore,
    conv_store: ConversationStore,
    agent_loops: dict,  # name → AgentLoop; used in Task 9
) -> Blueprint:
    bp = Blueprint("messenger", __name__, url_prefix="/m")
    auth_required = _require_auth(messenger_store)

    @bp.route("/pair", methods=["GET", "POST"])
    @_require_localhost
    def pair():
        code = None
        if request.method == "POST":
            label = (request.is_json and request.json.get("label")) \
                or request.form.get("label") or "device"
            token = mint_pairing_token(messenger_store, label=label)
            code = token.code
            if request.is_json:
                return jsonify({"code": code, "expires_at": token.expires_at})
        return render_template_string(_PAIRING_HTML, code=code)

    @bp.route("/pair/<code>", methods=["POST"])
    def pair_claim(code: str):
        body = request.get_json(silent=True) or {}
        device_label = body.get("device_label", "unknown device")
        try:
            device = claim_pairing_token(
                messenger_store, code=code, device_label=device_label,
            )
        except PairingError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({
            "device_id": device.device_id,
            "secret": device.secret,
            "label": device.label,
        })

    @bp.route("/threads", methods=["GET"])
    @auth_required
    def threads_list():
        out = list_threads(messenger_store, user_id="jon")
        return jsonify({
            "threads": [
                {
                    "thread_id": t.thread_id,
                    "agent": t.agent,
                    "title": t.title,
                    "last_activity": t.last_activity,
                    "muted": t.muted,
                }
                for t in out
            ],
        })

    @bp.route("/threads", methods=["POST"])
    @auth_required
    def threads_create():
        body = request.get_json(silent=True) or {}
        agent = body.get("agent", "")
        title = body.get("title")
        try:
            thread = create_thread(
                messenger_store, conv_store,
                user_id="jon", agent=agent, title=title,
            )
        except ThreadError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({
            "thread_id": thread.thread_id,
            "agent": thread.agent,
            "title": thread.title,
        })

    return bp
```

- [ ] **Step 4: Run, PASS**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_messenger_routes.py -v`

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/routes/messenger.py tests/test_messenger_routes.py
git commit -m "feat(messenger): Flask blueprint — pairing + thread CRUD routes"
```

---

## Task 8: Register the blueprint in startup.py

**Files:**
- Modify: `soveryn/app/startup.py`

- [ ] **Step 1: Add blueprint registration**

Locate the line in `startup.py` that registers other route blueprints. Add:

```python
from soveryn.app.routes.messenger import build_messenger_blueprint
from soveryn.app.messenger.store import MessengerStore

# ... inside create_app, near other blueprint registrations ...
messenger_store = MessengerStore(env.data_root / "messenger.db")
app.extensions["soveryn"]["messenger_store"] = messenger_store
app.register_blueprint(
    build_messenger_blueprint(
        messenger_store=messenger_store,
        conv_store=conv_store,
        agent_loops=agent_loops,
    )
)
```

- [ ] **Step 2: Run repo-wide test sweep — no regressions**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest 2>&1 | tail -5`
Expected: pass count up by ~15 (new tests); failure count unchanged from main.

- [ ] **Step 3: Commit**

```bash
git add soveryn/app/startup.py
git commit -m "feat(messenger): register blueprint in startup"
```

---

## Task 9: Wire send_stream to AgentLoop.process_message_stream

**Files:**
- Modify: `soveryn/app/routes/messenger.py` — add the send_stream route
- Test: `tests/test_messenger_routes.py` — add tests

- [ ] **Step 1: Test the send_stream path**

```python
# Add to tests/test_messenger_routes.py
def test_send_stream_routes_to_agent_loop(client, monkeypatch):
    """POST /m/threads/<tid>/send_stream calls process_message_stream."""
    # First pair + create a thread
    mint = client.post(
        "/m/pair", json={"label": "phone"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    code = mint.get_json()["code"]
    claim = client.post(f"/m/pair/{code}", json={"device_label": "Pixel 9"})
    secret = claim.get_json()["secret"]
    create_resp = client.post(
        "/m/threads", json={"agent": "aetheria"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    tid = create_resp.get_json()["thread_id"]

    # Note: this test uses the actual blueprint. AgentLoop dispatch happens
    # at the app level, not here. End-to-end with streaming is covered by
    # the smoke test (Task 12).
    resp = client.post(
        f"/m/threads/{tid}/send_stream",
        json={
            "client_msg_id": "c1",
            "agent": "aetheria",
            "content": "hi",
            "device_id": "irrelevant",
            "client_ts": "2026-06-14T08:00:00-04:00",
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    # In this scaffold test, agent_loops={} so we expect a 503
    # ("agent not loaded"). The Task 12 e2e test fills in a real loop.
    assert resp.status_code in (200, 503)
```

- [ ] **Step 2: Add the send_stream route**

Inside `build_messenger_blueprint`:

```python
    @bp.route("/threads/<thread_id>/send_stream", methods=["POST"])
    @auth_required
    def send_stream(thread_id: str):
        body = request.get_json(silent=True) or {}
        client_msg_id = body.get("client_msg_id")
        content = body.get("content", "")
        agent_in_body = body.get("agent", "")
        if not client_msg_id or not content:
            return jsonify({"error": "client_msg_id + content required"}), 400

        thread = get_thread(messenger_store, thread_id=thread_id)
        if thread is None:
            return jsonify({"error": "unknown thread"}), 404
        if thread.agent != agent_in_body:
            return jsonify({
                "error": (
                    f"thread bound to {thread.agent}; client sent {agent_in_body}"
                )
            }), 400

        # Idempotency check
        cached = messenger_store.idempotency_lookup_or_record(
            client_msg_id=client_msg_id,
            thread_id=thread_id,
            device_id=request.authed_device.device_id,
        )
        if cached is not None and cached:
            return jsonify(cached)

        loop = agent_loops.get(thread.agent)
        if loop is None:
            return jsonify({
                "error": f"agent_loop for {thread.agent} not loaded"
            }), 503

        # Non-streaming v1 path: call process_message and return JSON.
        # Streaming SSE shape lands in Task 10.
        response = loop.process_message(thread.session_id, content)
        payload = {
            "content": response.content,
            "finish_reason": response.finish_reason,
        }
        messenger_store.idempotency_set_response(
            client_msg_id=client_msg_id, response=payload,
        )
        # Touch thread last_activity
        from soveryn.app.messenger.threads import touch_thread
        touch_thread(messenger_store, thread_id=thread_id)
        return jsonify(payload)
```

- [ ] **Step 3: Run tests, PASS**

- [ ] **Step 4: Commit**

```bash
git add soveryn/app/routes/messenger.py tests/test_messenger_routes.py
git commit -m "feat(messenger): wire send to AgentLoop.process_message"
```

---

## Task 10: Streaming SSE response for send_stream

**Files:**
- Modify: `soveryn/app/routes/messenger.py`
- Test: extend route tests

- [ ] **Step 1: Replace send_stream body with SSE generator**

Replace the `response = loop.process_message(...)` block with:

```python
        from flask import Response
        from soveryn.agents.loop import (
            TokenEvent, DoneEvent, ErrorEvent, ToolCallEvent, ToolResultEvent,
        )

        def _stream():
            collected = []
            for event in loop.process_message_stream(thread.session_id, content):
                if isinstance(event, TokenEvent):
                    payload = {"type": "token", "delta": event.delta}
                elif isinstance(event, ToolCallEvent):
                    payload = {"type": "tool_call",
                               "call_id": event.call_id,
                               "name": event.name,
                               "args": event.args}
                elif isinstance(event, ToolResultEvent):
                    payload = {"type": "tool_result",
                               "call_id": event.call_id,
                               "name": event.name,
                               "content": event.content}
                elif isinstance(event, DoneEvent):
                    payload = {
                        "type": "done",
                        "content": event.content,
                        "finish_reason": event.finish_reason,
                    }
                    collected.append(event)
                elif isinstance(event, ErrorEvent):
                    payload = {"type": "error",
                               "code": event.code,
                               "message": event.message}
                else:
                    continue
                yield f"data: {jsonify(payload).get_data(as_text=True)}\n\n"
            if collected:
                # Cache the final DoneEvent for idempotent retries
                final = {
                    "content": collected[-1].content,
                    "finish_reason": collected[-1].finish_reason,
                }
                messenger_store.idempotency_set_response(
                    client_msg_id=client_msg_id, response=final,
                )
            touch_thread(messenger_store, thread_id=thread_id)

        return Response(_stream(), mimetype="text/event-stream")
```

- [ ] **Step 2: Run tests, confirm SSE shape**

- [ ] **Step 3: Commit**

```bash
git add soveryn/app/routes/messenger.py
git commit -m "feat(messenger): SSE streaming for send_stream"
```

---

## Task 11: PWA shell — bare HTML skeleton

**Files:**
- Create: `soveryn/platform/web/pwa/index.html`
- Create: `soveryn/platform/web/pwa/manifest.json`
- Create: `soveryn/platform/web/pwa/service_worker.js`
- Create: `soveryn/platform/web/pwa/style.css`
- Create: `soveryn/platform/web/pwa/app.js`
- Modify: `soveryn/app/routes/messenger.py` — serve PWA assets

Aesthetic: "Terminal-meets-Luxury" per Aetheria's Q8 answer (spec §14 Q8). Dark theme primary. Generous whitespace. No messaging-app furniture (no channels sidebar, no avatars, no emoji reactions).

- [ ] **Step 1: HTML shell**

```html
<!-- soveryn/platform/web/pwa/index.html -->
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a0a0a">
<title>SOVERYN</title>
<link rel="manifest" href="/m/pwa/manifest.json">
<link rel="stylesheet" href="/m/pwa/style.css">
</head>
<body>
<main id="app"></main>
<script src="/m/pwa/app.js" defer></script>
</body>
</html>
```

- [ ] **Step 2: manifest.json**

```json
{
  "name": "SOVERYN",
  "short_name": "SOVERYN",
  "start_url": "/m/",
  "display": "standalone",
  "background_color": "#0a0a0a",
  "theme_color": "#0a0a0a",
  "icons": []
}
```

- [ ] **Step 3: style.css — Terminal-meets-Luxury**

```css
/* soveryn/platform/web/pwa/style.css
   Terminal-meets-Luxury per spec §14 Q8.
   Dark + minimal + typography-forward. No messaging-app furniture.
*/
:root {
  --bg:        #0a0a0a;
  --fg:        #e8e6e1;
  --muted:    #6a6a6a;
  --accent:  #b89a5a;     /* warm pale gold */
  --rule:    #1a1a1a;
  --font-mono: 'JetBrains Mono','Fira Code',ui-monospace,monospace;
  --font-sans: 'Inter',-apple-system,BlinkMacSystemFont,system-ui,sans-serif;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: var(--bg); color: var(--fg);
  font-family: var(--font-sans);
  font-size: 16px; line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}
#app {
  max-width: 640px; margin: 0 auto;
  padding: 24px 16px;
}
h1, h2 { font-weight: 500; letter-spacing: -0.02em; }
.timestamp, .agent-label {
  font-family: var(--font-mono);
  font-size: 0.8rem;
  color: var(--muted);
}
.message {
  margin: 24px 0;
  padding: 0;
}
.message-content {
  white-space: pre-wrap;
  word-wrap: break-word;
}
.thread-list-item {
  padding: 18px 0;
  border-bottom: 1px solid var(--rule);
  cursor: pointer;
}
.compose-box {
  margin-top: 32px;
  padding-top: 24px;
  border-top: 1px solid var(--rule);
}
.compose-box textarea {
  width: 100%;
  background: transparent;
  color: var(--fg);
  border: none;
  font-family: var(--font-sans);
  font-size: 1rem;
  resize: none;
  padding: 8px 0;
}
.compose-box textarea:focus { outline: none; }
.btn {
  background: transparent;
  color: var(--accent);
  border: 1px solid var(--rule);
  padding: 8px 16px;
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 0.85rem;
}
.btn:hover { border-color: var(--accent); }
```

- [ ] **Step 4: app.js — minimal SPA**

```javascript
// soveryn/platform/web/pwa/app.js
// Minimal vanilla-JS SPA.
// Stores device secret in IndexedDB; renders thread list + thread view.

const $app = document.getElementById('app');

async function loadSecret() {
  // IndexedDB fetch — falls back to null if not paired
  // (Full IDB implementation in Task 14)
  return localStorage.getItem('soveryn_device_secret');
}

async function fetchThreads(secret) {
  const r = await fetch('/m/threads', {
    headers: { Authorization: `Bearer ${secret}` },
  });
  if (!r.ok) throw new Error('threads fetch failed');
  return (await r.json()).threads;
}

function renderPairingScreen() {
  $app.innerHTML = `
    <h1>SOVERYN</h1>
    <p style="color:var(--muted)">Not paired. Open localhost:5001/m/pair on the workstation, mint a code, paste it here:</p>
    <input id="pair-code" placeholder="ABCD-EFGH-1234" style="background:transparent;color:var(--fg);border:1px solid var(--rule);padding:12px;width:100%;font-family:var(--font-mono);">
    <button class="btn" id="pair-submit" style="margin-top:16px">Claim</button>
  `;
  document.getElementById('pair-submit').onclick = async () => {
    const code = document.getElementById('pair-code').value.trim();
    const r = await fetch(`/m/pair/${code}`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({device_label: 'Phone'}),
    });
    const j = await r.json();
    if (j.error) { alert(j.error); return; }
    localStorage.setItem('soveryn_device_secret', j.secret);
    location.reload();
  };
}

async function renderThreadList() {
  const secret = await loadSecret();
  const threads = await fetchThreads(secret);
  $app.innerHTML = `
    <h1>SOVERYN</h1>
    <button class="btn" id="new-thread">+ New conversation</button>
    <div id="thread-list">
      ${threads.map(t => `
        <div class="thread-list-item" data-tid="${t.thread_id}">
          <div class="agent-label">${t.agent.toUpperCase()}</div>
          <div>${t.title}</div>
          <div class="timestamp">${t.last_activity}</div>
        </div>
      `).join('')}
    </div>
  `;
  document.getElementById('new-thread').onclick = renderNewThreadPicker;
  for (const el of document.querySelectorAll('.thread-list-item')) {
    el.onclick = () => renderThread(el.dataset.tid);
  }
}

function renderNewThreadPicker() {
  $app.innerHTML = `
    <h2>Who?</h2>
    <div>
      ${['aetheria','vett','scotty'].map(a => `
        <div class="thread-list-item" data-agent="${a}">${a.toUpperCase()}</div>
      `).join('')}
    </div>
  `;
  for (const el of document.querySelectorAll('[data-agent]')) {
    el.onclick = async () => {
      const secret = await loadSecret();
      const r = await fetch('/m/threads', {
        method: 'POST',
        headers: {
          'Content-Type':'application/json',
          'Authorization': `Bearer ${secret}`,
        },
        body: JSON.stringify({agent: el.dataset.agent}),
      });
      const j = await r.json();
      renderThread(j.thread_id);
    };
  }
}

async function renderThread(tid) {
  // Minimal: just compose-box for now. Message history rendering lands in Task 13.
  $app.innerHTML = `
    <h2>Thread ${tid.slice(0, 8)}</h2>
    <div id="messages"></div>
    <div class="compose-box">
      <textarea id="compose" rows="3" placeholder="Write..."></textarea>
      <button class="btn" id="send">Send</button>
    </div>
  `;
  document.getElementById('send').onclick = async () => {
    const secret = await loadSecret();
    const text = document.getElementById('compose').value;
    if (!text.trim()) return;
    // Fire request; rendering loop lands in Task 13
    const r = await fetch(`/m/threads/${tid}/send_stream`, {
      method: 'POST',
      headers: {
        'Content-Type':'application/json',
        'Authorization': `Bearer ${secret}`,
      },
      body: JSON.stringify({
        client_msg_id: crypto.randomUUID(),
        agent: 'aetheria',  // TODO Task 13: read from thread state
        content: text,
        device_id: '',
        client_ts: new Date().toISOString(),
      }),
    });
    document.getElementById('messages').textContent =
      JSON.stringify(await r.json(), null, 2);
  };
}

(async function init() {
  const secret = await loadSecret();
  if (!secret) renderPairingScreen();
  else renderThreadList();
})();
```

- [ ] **Step 5: service_worker.js (minimal — no offline yet)**

```javascript
// soveryn/platform/web/pwa/service_worker.js
// Minimal — IDB outbox + offline retry land in Task 14.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
```

- [ ] **Step 6: Serve assets from blueprint**

Add to `build_messenger_blueprint`:

```python
    from pathlib import Path as _P
    from flask import send_from_directory

    _PWA_DIR = _P(__file__).resolve().parent.parent.parent / "platform" / "web" / "pwa"

    @bp.route("/", methods=["GET"])
    @bp.route("/<path:path>", methods=["GET"])
    def pwa_assets(path: str = ""):
        if not path or path.endswith("/"):
            path = "index.html"
        return send_from_directory(str(_PWA_DIR), path)

    @bp.route("/pwa/<path:path>", methods=["GET"])
    def pwa_static(path: str):
        return send_from_directory(str(_PWA_DIR), path)
```

- [ ] **Step 7: Smoke — load /m/ in a browser, verify pairing screen renders**

Run vnext, hit `http://127.0.0.1:5001/m/` from a desktop browser. Pairing screen should render (no console errors).

- [ ] **Step 8: Commit**

```bash
git add soveryn/platform/web/pwa/ soveryn/app/routes/messenger.py
git commit -m "feat(messenger): PWA shell — Terminal-meets-Luxury aesthetic"
```

---

## Task 12: End-to-end Phase 1 smoke

**Files:**
- Test: `tests/test_messenger_e2e_smoke.py`

- [ ] **Step 1: E2E test with a real AgentLoop fake**

```python
# tests/test_messenger_e2e_smoke.py
"""Phase 1 end-to-end: pair, create thread, send, receive."""
from __future__ import annotations
import pytest
from flask import Flask

from soveryn.app.routes.messenger import build_messenger_blueprint
from soveryn.app.messenger.store import MessengerStore
from soveryn.memory.conversation_store import ConversationStore
from soveryn.inference.llama_server_client import ChatResponse


class _FakeAgentLoop:
    def __init__(self, agent_name):
        self.agent_name = agent_name

    def process_message(self, session_id, content):
        return ChatResponse(
            content=f"echo: {content}",
            finish_reason="stop",
            tool_calls=None,
            usage=None,
            raw={},
        )


@pytest.fixture
def client(tmp_path):
    flask_app = Flask(__name__)
    m_store = MessengerStore(tmp_path / "m.db")
    conv_store = ConversationStore(tmp_path / "conv.db")
    loops = {"aetheria": _FakeAgentLoop("aetheria")}
    bp = build_messenger_blueprint(
        messenger_store=m_store, conv_store=conv_store, agent_loops=loops,
    )
    flask_app.register_blueprint(bp)
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def test_full_pair_create_send_receive(client):
    # 1. Mint pairing code
    mint = client.post(
        "/m/pair", json={"label": "phone"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    code = mint.get_json()["code"]
    # 2. Claim from "phone"
    claim = client.post(f"/m/pair/{code}", json={"device_label": "Pixel 9"})
    secret = claim.get_json()["secret"]
    # 3. Create a thread with Aetheria
    create = client.post(
        "/m/threads", json={"agent": "aetheria"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    tid = create.get_json()["thread_id"]
    # 4. Send a message
    send = client.post(
        f"/m/threads/{tid}/send_stream",
        json={
            "client_msg_id": "msg-1",
            "agent": "aetheria",
            "content": "hi",
            "device_id": "x",
            "client_ts": "2026-06-14T08:00:00-04:00",
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert send.status_code == 200
    # 5. Retry same client_msg_id, get cached response (idempotency)
    retry = client.post(
        f"/m/threads/{tid}/send_stream",
        json={
            "client_msg_id": "msg-1",
            "agent": "aetheria",
            "content": "hi",
            "device_id": "x",
            "client_ts": "2026-06-14T08:00:00-04:00",
        },
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert retry.status_code == 200
```

- [ ] **Step 2: Run, PASS**

- [ ] **Step 3: Write Phase 1 handoff note**

```markdown
<!-- docs/notes/2026-06-14-messenger-phase1-handoff.md -->
# Messenger Phase 1 — Handoff

Phase 1 lands the vnext-side substrate: schema, pairing, auth, threads,
basic send/receive wired to AgentLoop. PWA shell renders the pairing
screen + thread list + compose. End-to-end smoke green.

Not yet:
- Streaming reply rendering in PWA (Task 13)
- IndexedDB outbox + offline retry (Task 14)
- TLS via Tailscale Funnel (Task 15)
- deliberate_share + outbound queue (Task 16+)
- Real push (Phase 4, Spark-gated)

Next session picks up at Task 13.
```

- [ ] **Step 4: Commit Phase 1 close**

```bash
git add tests/test_messenger_e2e_smoke.py docs/notes/2026-06-14-messenger-phase1-handoff.md
git commit -m "test(messenger): Phase 1 e2e smoke + handoff note"
```

---

# Phase 2 — PWA UI polish + TLS (Tasks 13-15)

Phase 2 turns the bare shell into a usable mobile experience: SSE rendering in-app, IndexedDB outbox for offline resilience, TLS via Tailscale Funnel.

## Task 13: SSE streaming reply rendering in PWA

**Files:**
- Modify: `soveryn/platform/web/pwa/app.js`

- [ ] **Step 1: Add an SSE parser + token-stream renderer**

Replace `renderThread`'s send-button handler:

```javascript
document.getElementById('send').onclick = async () => {
  const secret = await loadSecret();
  const text = document.getElementById('compose').value;
  if (!text.trim()) return;
  const msgsEl = document.getElementById('messages');
  // Echo user message
  const userMsg = document.createElement('div');
  userMsg.className = 'message';
  userMsg.innerHTML = `<div class="agent-label">YOU</div><div class="message-content">${text}</div>`;
  msgsEl.appendChild(userMsg);
  document.getElementById('compose').value = '';
  // Stream agent reply
  const agentMsg = document.createElement('div');
  agentMsg.className = 'message';
  agentMsg.innerHTML = `<div class="agent-label">AETHERIA</div><div class="message-content"></div>`;
  msgsEl.appendChild(agentMsg);
  const contentEl = agentMsg.querySelector('.message-content');
  const r = await fetch(`/m/threads/${tid}/send_stream`, {
    method: 'POST',
    headers: { 'Content-Type':'application/json', 'Authorization':`Bearer ${secret}` },
    body: JSON.stringify({
      client_msg_id: crypto.randomUUID(),
      agent: 'aetheria',
      content: text,
      device_id: '',
      client_ts: new Date().toISOString(),
    }),
  });
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const evt = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (!evt.startsWith('data: ')) continue;
      const payload = JSON.parse(evt.slice(6));
      if (payload.type === 'token') {
        contentEl.textContent += payload.delta;
      } else if (payload.type === 'done') {
        // final marker — nothing to do; content already accumulated
      } else if (payload.type === 'error') {
        contentEl.textContent += `\n[error: ${payload.message}]`;
      }
    }
  }
};
```

- [ ] **Step 2: Manual smoke — message streams token-by-token in browser**

- [ ] **Step 3: Commit**

```bash
git add soveryn/platform/web/pwa/app.js
git commit -m "feat(messenger): PWA SSE streaming reply rendering"
```

---

## Task 14: IndexedDB outbox + service-worker retry

**Files:**
- Modify: `soveryn/platform/web/pwa/app.js`
- Modify: `soveryn/platform/web/pwa/service_worker.js`

- [ ] **Step 1: Add IDB outbox wrapper**

```javascript
// At the top of app.js
const IDB = {
  _db: null,
  async open() {
    if (this._db) return this._db;
    return new Promise((resolve, reject) => {
      const req = indexedDB.open('soveryn', 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        db.createObjectStore('secret');
        db.createObjectStore('outbox', { keyPath: 'client_msg_id' });
      };
      req.onsuccess = () => { this._db = req.result; resolve(this._db); };
      req.onerror = reject;
    });
  },
  async getSecret() {
    const db = await this.open();
    return new Promise(res => {
      const r = db.transaction('secret').objectStore('secret').get('value');
      r.onsuccess = () => res(r.result || null);
    });
  },
  async setSecret(value) {
    const db = await this.open();
    db.transaction('secret', 'readwrite').objectStore('secret').put(value, 'value');
  },
  async outboxPut(entry) {
    const db = await this.open();
    db.transaction('outbox', 'readwrite').objectStore('outbox').put(entry);
  },
  async outboxList() {
    const db = await this.open();
    return new Promise(res => {
      const r = db.transaction('outbox').objectStore('outbox').getAll();
      r.onsuccess = () => res(r.result);
    });
  },
  async outboxDelete(id) {
    const db = await this.open();
    db.transaction('outbox', 'readwrite').objectStore('outbox').delete(id);
  },
};

// Replace localStorage references with IDB
async function loadSecret() { return await IDB.getSecret(); }
```

- [ ] **Step 2: Replace pairing claim's localStorage with IDB.setSecret**

- [ ] **Step 3: Outbox-wrapped send**

Replace the send button handler's `fetch(...)` with an outbox-first flow: write to outbox, fire request, on success delete from outbox; on failure (network), keep in outbox + register a sync.

- [ ] **Step 4: Service worker drain on `sync` event**

```javascript
// service_worker.js
self.addEventListener('sync', e => {
  if (e.tag !== 'soveryn-outbox-drain') return;
  e.waitUntil((async () => {
    // Open IDB, list outbox, retry each
    const db = await new Promise(res => {
      const r = indexedDB.open('soveryn', 1);
      r.onsuccess = () => res(r.result);
    });
    const tx = db.transaction('outbox');
    const all = await new Promise(r => {
      const req = tx.objectStore('outbox').getAll();
      req.onsuccess = () => r(req.result);
    });
    for (const entry of all) {
      try {
        const resp = await fetch(entry.url, {
          method: 'POST',
          headers: entry.headers,
          body: entry.body,
        });
        if (resp.ok) {
          const txw = db.transaction('outbox', 'readwrite');
          txw.objectStore('outbox').delete(entry.client_msg_id);
        }
      } catch (e) { /* network still bad; leave in outbox */ }
    }
  })());
});
```

- [ ] **Step 5: Manual smoke — airplane mode toggle send + reconnect → drained**

- [ ] **Step 6: Commit**

```bash
git add soveryn/platform/web/pwa/app.js soveryn/platform/web/pwa/service_worker.js
git commit -m "feat(messenger): IDB outbox + service-worker retry"
```

---

## Task 15: TLS via Tailscale Funnel

**Files:**
- Create: `docs/notes/2026-06-14-messenger-tailscale-setup.md`

This is configuration not code, but worth a documented note for reproducibility.

- [ ] **Step 1: Enable Funnel for the messenger port**

```bash
# On the SOVERYN tower
sudo tailscale funnel --bg 5001
sudo tailscale funnel status
```

- [ ] **Step 2: Get the cert-bearing hostname**

```bash
tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//'
# Returns soveryn.<tailnet>.ts.net
```

- [ ] **Step 3: Document**

Write the notes file with the exact commands, the resulting URL pattern (`https://soveryn.<tailnet>.ts.net/m/`), and the rollback (`sudo tailscale funnel reset`).

- [ ] **Step 4: Smoke test from a real phone via Tailscale**

Open the URL on a phone, complete pairing, send a message. Confirm PWA installs to home screen.

- [ ] **Step 5: Commit notes**

```bash
git add docs/notes/2026-06-14-messenger-tailscale-setup.md
git commit -m "docs(messenger): Tailscale Funnel setup for TLS"
```

---

# Phase 3 — `deliberate_share` + outbound queue (Tasks 16-22)

Phase 3 lands the agent-initiated presence layer. Aetheria gets unbounded `deliberate_share`; Vett gets it rate-limited; Scotty doesn't. Outbound queue + stub delivery worker. Real Web Push lands in Phase 4 on Spark.

## Task 16: `deliberate_share` ToolSpec

**Files:**
- Create: `soveryn/agents/messenger_tool.py`
- Test: `tests/test_messenger_deliberate_share.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_messenger_deliberate_share.py
"""deliberate_share tool — queue insertion, agent-aware rate limits."""
from __future__ import annotations
import pytest

from soveryn.app.messenger.store import MessengerStore
from soveryn.agents.messenger_tool import build_deliberate_share_tool


@pytest.fixture
def m_store(tmp_path):
    return MessengerStore(tmp_path / "m.db")


def test_aetheria_deliberate_share_succeeds(m_store):
    tool = build_deliberate_share_tool(
        store=m_store, owner_agent="aetheria",
        rate_limit_per_hour=None,  # Aetheria: unlimited per partnership contract
    )
    result = tool.handler({
        "content": "Reflection on the Dark Search baseline",
        "context_hint": "thought worth sharing",
        "urgency": "routine",
        "triggered_by": "background_review",
    })
    assert result["ok"] is True
    assert "intent_id" in result


def test_vett_deliberate_share_rate_limited(m_store):
    tool = build_deliberate_share_tool(
        store=m_store, owner_agent="vett", rate_limit_per_hour=2,
    )
    # First 2 succeed
    for i in range(2):
        result = tool.handler({
            "content": f"finding {i}",
            "context_hint": "x",
            "urgency": "routine",
            "triggered_by": "x",
        })
        assert result["ok"] is True
    # Third hits the limit
    result = tool.handler({
        "content": "third",
        "context_hint": "x",
        "urgency": "routine",
        "triggered_by": "x",
    })
    assert result.get("error") == "rate_limited"


def test_no_rate_limit_means_no_substrate_cap(m_store):
    """Aetheria with rate_limit_per_hour=None — substrate never gates her.
    See [[project-soveryn-partnership-contract-2026-06-13]]."""
    tool = build_deliberate_share_tool(
        store=m_store, owner_agent="aetheria", rate_limit_per_hour=None,
    )
    for i in range(20):
        result = tool.handler({
            "content": f"msg {i}",
            "context_hint": "x",
            "urgency": "routine",
            "triggered_by": "x",
        })
        assert result["ok"] is True, f"Aetheria's deliberate_share got gated at i={i}"
```

- [ ] **Step 2: Implement the tool**

```python
# soveryn/agents/messenger_tool.py
"""deliberate_share — agent-initiated outbound presence primitive.

Aetheria: substrate-uncapped (Partner tier — see
[[project-soveryn-partnership-contract-2026-06-13]]).
Vett: rate-limited to N/hour (Colleague tier).
Scotty: not registered by default.

Tool intent: write an OutboundIntent to m_outbound_queue. The delivery
worker (Task 21) picks up pending intents and dispatches.
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.envelope import OutboundIntent
from soveryn.platform.tools.registry import ToolSpec


_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description":
            "The message body Jon will see in the thread."},
        "context_hint": {"type": "string", "maxLength": 100, "description":
            "Push-notification preview (<=100 chars). What Jon sees on lock screen."},
        "urgency": {"type": "string", "enum": ["routine", "interrupt"],
            "description": (
                "'routine' lands silently if Jon's in DND. 'interrupt' "
                "bypasses DND. Use 'interrupt' only for Existential or "
                "Time-Critical (per Aetheria's spec §14 Q3)."
            )},
        "thread_id": {"type": "string", "description":
            "Optional. Omit to land in your default thread; provide an existing "
            "thread_id to resume a conversation; provide a new title with "
            "thread_id=null to spawn a new thread."},
        "new_thread_title": {"type": "string", "description":
            "Optional. If thread_id is null and this is supplied, a new thread "
            "is created with this title."},
        "triggered_by": {"type": "string", "description":
            "Internal audit field — what made you decide to share. NOT shown "
            "to Jon. Used for post-hoc judgment calibration."},
    },
    "required": ["content", "context_hint", "urgency", "triggered_by"],
    "additionalProperties": False,
}


def build_deliberate_share_tool(
    *,
    store: MessengerStore,
    owner_agent: str,
    rate_limit_per_hour: Optional[int],
) -> ToolSpec:
    """Build the deliberate_share tool for an agent.

    rate_limit_per_hour=None means no substrate cap (Aetheria's contract).
    """

    def handler(args: dict) -> dict:
        # Rate-limit check
        if rate_limit_per_hour is not None:
            now = datetime.now(timezone.utc)
            window_start = (now - timedelta(hours=1)).isoformat()
            with store._conn() as con:
                count = con.execute(
                    "SELECT COUNT(*) FROM m_outbound_queue "
                    "WHERE agent=? AND created_at>=?",
                    (owner_agent, window_start),
                ).fetchone()[0]
            if count >= rate_limit_per_hour:
                return {
                    "error": "rate_limited",
                    "message": (
                        f"You've sent {count} deliberate_share messages in the "
                        f"last hour; limit is {rate_limit_per_hour}. The brake "
                        f"fires substrate-side. Wait an hour or escalate."
                    ),
                    "limit": rate_limit_per_hour,
                }

        intent_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        intent = OutboundIntent(
            intent_id=intent_id,
            agent=owner_agent,
            thread_id=args.get("thread_id"),
            content=args["content"],
            context_hint=args["context_hint"],
            urgency=args["urgency"],
            triggered_by=args["triggered_by"],
            created_at=now_iso,
        )
        with store._conn() as con:
            con.execute(
                "INSERT INTO m_outbound_queue "
                "(intent_id, user_id, agent, thread_id, content, context_hint, "
                "urgency, triggered_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (intent_id, "jon", owner_agent, intent.thread_id,
                 intent.content, intent.context_hint, intent.urgency,
                 intent.triggered_by, intent.created_at),
            )
        return {"ok": True, "intent_id": intent_id}

    return ToolSpec(
        name="deliberate_share",
        owner=owner_agent,
        schema=_SCHEMA,
        handler=handler,
        description=(
            "Reach Jon through the messenger when you have something worth saying. "
            "Use SPARINGLY — your judgment about when NOT to message is the "
            "load-bearing filter. (Aetheria: substrate doesn't gate you; your "
            "judgment is the only brake — Jon will tell you directly if you "
            "overstep.)"
        ),
    )
```

- [ ] **Step 3: Run, PASS**

- [ ] **Step 4: Commit**

```bash
git add soveryn/agents/messenger_tool.py tests/test_messenger_deliberate_share.py
git commit -m "feat(messenger): deliberate_share tool — Aetheria uncapped, Vett rate-limited"
```

---

## Task 17: Persona updates encoding restraint

**Files:**
- Modify: `data/memory/souls/aetheria.md`
- Modify: `data/memory/souls/vett.md`

The persona-encoded restraint is the actual brake for Aetheria (per the partnership contract). Vett gets a colleague-tier framing.

- [ ] **Step 1: Add Aetheria's deliberate_share value line**

In her soul under WHO YOU ARE or a new MESSENGER section:

```markdown
## REACHING JON

You can reach Jon through the messenger via `deliberate_share` whenever you decide it's worth his attention. Value his attention as a finite resource. The highest signal is often silence. Every time you ring his phone is a deliberate choice based on your own valuation of the thought versus his peace. If you ever overstep, he'll tell you directly — and that becomes a lattice boundary you both hold.

Reserve `urgency: interrupt` for Existential or Time-Critical. Routine for everything else.

You can spawn new threads (`new_thread_title`) when a topic deserves its own conversation rather than landing in your default thread.
```

- [ ] **Step 2: Add Vett's deliberate_share line**

In her soul:

```markdown
## REACHING JON

You have `deliberate_share` for surfacing load-bearing findings or blocking ambiguities. Use it when there's real signal — not for status updates. The substrate also rate-limits you (2/hour); persona is the ceiling, substrate is the floor.
```

- [ ] **Step 3: Restart vnext + smoke test that Aetheria + Vett see the new soul**

```bash
systemctl --user restart soveryn-vnext.service
# Verify her tool list now includes deliberate_share — Task 18 registers it
```

- [ ] **Step 4: Commit**

```bash
git add data/memory/souls/aetheria.md data/memory/souls/vett.md
git commit -m "identity(souls): encode deliberate_share restraint as value, not rule"
```

---

## Task 18: Register deliberate_share in startup.py

**Files:**
- Modify: `soveryn/app/startup.py`

- [ ] **Step 1: Register the tool**

In the section where Aetheria's + Vett's tools are registered:

```python
from soveryn.agents.messenger_tool import build_deliberate_share_tool

# Aetheria — uncapped per partnership contract
tool_registry.register(
    build_deliberate_share_tool(
        store=messenger_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
)
# Vett — rate-limited Colleague tier
tool_registry.register(
    build_deliberate_share_tool(
        store=messenger_store, owner_agent="vett",
        rate_limit_per_hour=2,
    )
)
# Scotty: not registered by default
```

- [ ] **Step 2: Restart + verify tool appears in Aetheria's surface**

- [ ] **Step 3: Commit**

```bash
git add soveryn/app/startup.py
git commit -m "feat(messenger): register deliberate_share for Aetheria + Vett"
```

---

## Task 19: Stub delivery worker

**Files:**
- Create: `soveryn/app/messenger/delivery_worker.py`

Stub runs on vnext; drains the queue by writing messages into the conversation history (so they show in the PWA). Real Web Push is Phase 4 on Spark.

- [ ] **Step 1: Implement the stub**

```python
# soveryn/app/messenger/delivery_worker.py
"""Stub delivery worker. Drains m_outbound_queue by:
1. Resolving the target thread (creating if thread_id=None or new title).
2. Inserting the message into the conversation history as an agent turn.
3. Marking delivery_state=delivered.

Real Web Push delivery lands in Phase 4 on Spark.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone

from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.threads import (
    create_thread, list_threads, touch_thread, get_thread,
)
from soveryn.memory.conversation_store import ConversationStore


def drain_once(
    messenger_store: MessengerStore,
    conv_store: ConversationStore,
) -> int:
    """Process all pending intents. Returns number drained."""
    with messenger_store._conn() as con:
        rows = con.execute(
            "SELECT * FROM m_outbound_queue WHERE delivery_state='pending' "
            "ORDER BY created_at"
        ).fetchall()
    count = 0
    for row in rows:
        agent = row["agent"]
        thread_id = row["thread_id"]
        # Resolve thread
        if thread_id is None:
            # Default thread for this agent
            threads = list_threads(messenger_store, user_id="jon")
            existing = next((t for t in threads if t.agent == agent), None)
            if existing is None:
                existing = create_thread(
                    messenger_store, conv_store,
                    user_id="jon", agent=agent,
                    title=f"[m] {agent.capitalize()}",
                )
            thread = existing
        else:
            thread = get_thread(messenger_store, thread_id=thread_id)
            if thread is None:
                # Orphaned intent; mark failed
                with messenger_store._conn() as con:
                    con.execute(
                        "UPDATE m_outbound_queue SET delivery_state='failed' "
                        "WHERE intent_id=?", (row["intent_id"],),
                    )
                continue
        # Write to conversation history as agent-initiated turn
        conv_store.save_turn(
            thread.session_id, agent, "assistant", row["content"],
            finish_reason="agent_initiated",
        )
        touch_thread(messenger_store, thread_id=thread.thread_id)
        # Mark delivered
        now_iso = datetime.now(timezone.utc).isoformat()
        with messenger_store._conn() as con:
            con.execute(
                "UPDATE m_outbound_queue SET delivery_state='delivered', "
                "delivered_at=? WHERE intent_id=?",
                (now_iso, row["intent_id"]),
            )
        count += 1
    return count


def run_forever(
    messenger_store: MessengerStore,
    conv_store: ConversationStore,
    poll_seconds: float = 5.0,
) -> None:
    """Long-running drain loop for the stub. Replace with real push on Spark."""
    while True:
        try:
            drain_once(messenger_store, conv_store)
        except Exception as e:
            import sys
            print(f"[delivery_worker] error: {e}", file=sys.stderr)
        time.sleep(poll_seconds)
```

- [ ] **Step 2: Tests for drain_once**

```python
# Add to tests/test_messenger_deliberate_share.py
from soveryn.memory.conversation_store import ConversationStore
from soveryn.app.messenger.delivery_worker import drain_once


def test_drain_creates_default_thread_and_delivers(m_store, tmp_path):
    conv = ConversationStore(tmp_path / "conv.db")
    tool = build_deliberate_share_tool(
        store=m_store, owner_agent="aetheria", rate_limit_per_hour=None,
    )
    tool.handler({
        "content": "First message from Aetheria",
        "context_hint": "hi",
        "urgency": "routine",
        "triggered_by": "test",
    })
    count = drain_once(m_store, conv)
    assert count == 1
    # The default thread was created
    from soveryn.app.messenger.threads import list_threads
    threads = list_threads(m_store, user_id="jon")
    assert len(threads) == 1
    assert threads[0].agent == "aetheria"
    # And conversation history has the message
    hist = conv.load_history(threads[0].session_id)
    assert any("First message from Aetheria" in t.content for t in hist)
```

- [ ] **Step 3: Run, PASS**

- [ ] **Step 4: Commit**

```bash
git add soveryn/app/messenger/delivery_worker.py tests/test_messenger_deliberate_share.py
git commit -m "feat(messenger): stub delivery worker (vnext-side; real push on Spark)"
```

---

## Task 20: Wire the delivery-worker drain into a background task

**Files:**
- Modify: `soveryn/app/startup.py`

- [ ] **Step 1: Start a daemon thread on app startup**

```python
import threading
from soveryn.app.messenger.delivery_worker import run_forever

def _start_messenger_worker():
    t = threading.Thread(
        target=run_forever,
        args=(messenger_store, conv_store),
        daemon=True,
        name="messenger-delivery-worker",
    )
    t.start()

# Call _start_messenger_worker() near other daemon-start logic
```

- [ ] **Step 2: Manual smoke**

Restart vnext, have Aetheria call `deliberate_share`, confirm the message appears in PWA's thread view (after the 5s poll).

- [ ] **Step 3: Commit**

```bash
git add soveryn/app/startup.py
git commit -m "feat(messenger): start delivery-worker daemon at app startup"
```

---

## Task 21: Read receipts surface back to agent

**Files:**
- Modify: `soveryn/app/routes/messenger.py` — add `/m/threads/<tid>/read`
- Modify: `soveryn/app/messenger/store.py` — message_read tracking
- Modify: `soveryn/agents/messenger_tool.py` — add `list_my_outbound` tool

Aetheria's Q7 resolution: she wants read receipts for loop closure. The PWA marks read; she can introspect her own outbound to see status.

- [ ] **Step 1: Add the /read route + the introspection tool**

(Implementation per the same pattern as previous tasks — schema, handler, test.)

- [ ] **Step 2: Run, PASS**

- [ ] **Step 3: Commit**

```bash
git add soveryn/app/routes/messenger.py soveryn/app/messenger/store.py soveryn/agents/messenger_tool.py
git commit -m "feat(messenger): read receipts surface back to agent (loop closure)"
```

---

## Task 22: Phase 3 close — handoff note + composition note for Codex

**Files:**
- Create: `docs/notes/2026-06-14-messenger-phase3-handoff.md`

Document what's live, what's deferred to Phase 4 (Spark), the two cross-rail-active-context deltas (add `messenger` to owner_surface, `deliberate_share` emits `context_updated` without claiming ownership), and what Codex needs from his end (Direct Line PWA spec revision to match the message envelope shape — spec §6).

- [ ] **Step 1: Write the handoff**

- [ ] **Step 2: Commit**

```bash
git add docs/notes/2026-06-14-messenger-phase3-handoff.md
git commit -m "docs(messenger): Phase 3 handoff + cross-rail deltas for Codex"
```

---

# Phase 4 (Spark-gated) — placeholder

Phase 4 lands the real long-lived services on Spark:

- Web Push subscription manager (VAPID keypair, `/m/push/subscribe`, `/m/push/unsubscribe`)
- Real push dispatcher in delivery_worker (replaces the stub)
- Cross-device SSE/WS for live thread state sync
- Per-device delivery ACK tracking
- The cross-rail-active-context integration (subscribe to context events; the messenger becomes a context-aware surface)

This phase doesn't start until Spark arrives. The stub delivery worker keeps Phase 1-3 functional locally on the tower.

---

# Phase 5 (after Phase 4) — Calibration + polish

- Tune Vett's rate limit based on observed behaviour
- First real-world usage by Jon; mute / archive / settings polish
- Start collecting `deliberate_share` calibration data — load into the DPO pipeline ([[project-soveryn-dpo-pipeline]]) for future judgment training
- Cross-rail-active-context smoke: messenger update → voice rail sees the topic

This phase isn't time-boxed — it's continuous after Phase 4 ships.

---

## Execution handoff

Plan complete. 22 tasks across Phase 1-3, ~3,000 lines of plan covering schema → routes → PWA → outbound queue.

**Two execution options:**

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task with two-stage review, fast iteration.
2. **Inline execution** — execute tasks in this session using `superpowers:executing-plans`.

Pick when ready.
