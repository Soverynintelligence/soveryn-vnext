# Heartbeat source-tag fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stop the heartbeat daemon's pulse turns from being persisted as `source='direct'` (which the UI renders as "primary" chat); tag them `source='heartbeat'` going forward, and re-tag the historical pulse turns.

**Architecture:** Thread an optional `source` param from the `/chat` route → `AgentLoop.process_message` → `ConversationStore.save_turn` (which already accepts `source`), and have the heartbeat's `_call_vnext_chat` pass `source="heartbeat"`. Then a one-time, surgical DB migration re-tags historical heartbeat-pulse turns in the `[heartbeat] aetheria` session while preserving the real human turns that happen to live there.

**Tech Stack:** Python 3.11 (soveryn env), Flask, sqlite3, pytest.

## Global Constraints

- Run everything with `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python` (3.11), from repo root `/home/jon-deoliveira/soveryn_vnext`.
- `source` default MUST remain `"direct"` at every layer — human chat behavior is unchanged; only the heartbeat opts into `"heartbeat"`.
- `ConversationStore.save_turn(session_id, agent, role, content, source="direct", finish_reason=None)` already supports `source` — do NOT change the store layer.
- The migration MUST NOT retag real human turns. In the `[heartbeat] aetheria` session, only `[HEARTBEAT]`-prefixed user turns and the assistant turn(s) that answer them become `heartbeat`; the 24 real June turns (06-05, 06-15) and their assistant responses stay `direct`.
- The migration MUST back up `data/memory/conversations_vnext.db` before writing, and report before/after counts.

---

## Task 1: Thread `source` through the chat path

**Files:**
- Modify: `soveryn/agents/loop.py` — `process_message` (~804) and `process_message_stream` (~1225): add `source: str = "direct"` param; pass `source=source` to the user-turn `save_turn` (`:856`, `:1269`) and the assistant-turn `save_turn` (`:1114`, `:1660`).
- Modify: `soveryn/app/routes/chat.py` — `chat()` (~238) and `chat_stream()` (~356): read `source = body.get("source", "direct")` (validate str, else 400) and pass to `process_message` / `process_message_stream`.
- Modify: `soveryn/agents/heartbeat/daemon.py` — `_call_vnext_chat` (`:788`): add `"source": "heartbeat"` to the payload.
- Test: `tests/test_heartbeat_source_tag.py` (new) + extend `tests/test_agent_loop*.py` if a natural home exists.

**Interfaces:**
- Produces: `process_message(session_id, user_message, attachments=None, *, source="direct")`; `/chat` and `/chat_stream` accept optional body `source`.

- [ ] **Step 1: Write the failing test** (behavior: a source passed to process_message tags BOTH turns)

```python
# tests/test_heartbeat_source_tag.py
from soveryn.memory.conversation_store import ConversationStore


def _loop(tmp_path, fake_chat):
    # Reuse the project's existing AgentLoop test harness/fixtures.
    ...  # implementer: construct an AgentLoop with a fake chat client, per existing loop tests


def test_process_message_tags_both_turns_with_source(tmp_path, loop_with_fake_chat):
    loop, store = loop_with_fake_chat
    sid = store.new_session("aetheria", title="[heartbeat] aetheria")
    loop.process_message(sid, "[HEARTBEAT] pulse", source="heartbeat")
    rows = store.load_history(sid)
    assert [r.source for r in rows] == ["heartbeat", "heartbeat"]  # user + assistant


def test_process_message_defaults_to_direct(tmp_path, loop_with_fake_chat):
    loop, store = loop_with_fake_chat
    sid = store.new_session("aetheria")
    loop.process_message(sid, "hello")
    rows = store.load_history(sid)
    assert all(r.source == "direct" for r in rows)
```

(Implementer: adapt to the existing AgentLoop test fixtures — a fake chat client that returns a fixed assistant content. Follow `tests/test_agent_loop*.py` patterns. Confirm `load_history` rows expose `.source`; if not, assert via a direct `SELECT source FROM conversations`.)

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_heartbeat_source_tag.py -v` → FAIL (`process_message` has no `source` kwarg).
- [ ] **Step 3: Implement** — add `source` param + thread it (see Files). Keep default `"direct"`.
- [ ] **Step 4: Run to verify it passes** — `pytest tests/test_heartbeat_source_tag.py -v` → PASS. Also run `tests/test_agent_loop*.py tests/test_chat_route*.py` to confirm no regression, and `ruff check` the 3 modified modules.
- [ ] **Step 5: Commit** — `git commit -m "fix(heartbeat): tag pulse turns source=heartbeat through the chat path"`

---

## Task 2: One-time surgical re-tag of historical pulse turns

**Files:**
- Create: `scripts/migrations/2026-07-18-retag-heartbeat-source.py` — pure, testable retag function + a `main()` that backs up the DB, runs it, prints before/after counts.
- Test: `tests/test_retag_heartbeat_migration.py`

**Interfaces:**
- Produces: `retag_heartbeat_turns(conn) -> dict` — mutates `conversations`, returns `{"retagged": int, "left_direct": int}`. A turn is a heartbeat turn iff it is in a session titled `[heartbeat] aetheria` AND (it is a `user` turn with content starting `[HEARTBEAT]`, OR it is an `assistant` turn whose most-recent preceding user turn in that session — by rowid order — starts `[HEARTBEAT]`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_retag_heartbeat_migration.py
import sqlite3
from scripts.migrations import importlib  # implementer: import the module by path

def _mk(conn):
    conn.executescript("""
      CREATE TABLE conversation_meta(session_id TEXT, agent TEXT, title TEXT, created_at TEXT, updated_at TEXT);
      CREATE TABLE conversations(session_id TEXT, agent TEXT, role TEXT, content TEXT, timestamp TEXT, source TEXT, finish_reason TEXT);
    """)
    conn.execute("INSERT INTO conversation_meta VALUES('hb','aetheria','[heartbeat] aetheria','t','t')")
    conn.execute("INSERT INTO conversation_meta VALUES('real','aetheria','morning chat','t','t')")
    # heartbeat session: pulse pair, then a REAL human interjection pair, then another pulse pair
    rows = [
      ('hb','aetheria','user','[HEARTBEAT] pulse 1','t1','direct',None),
      ('hb','aetheria','assistant','I spent this pulse...','t2','direct','stop'),
      ('hb','aetheria','user','hey are you ok?','t3','direct',None),          # REAL — must stay direct
      ('hb','aetheria','assistant','yes, I am here','t4','direct','stop'),      # REAL response — must stay direct
      ('hb','aetheria','user','[HEARTBEAT] pulse 2','t5','direct',None),
      ('hb','aetheria','assistant','I spent this pulse...','t6','direct','stop'),
      ('real','aetheria','user','hello','t7','direct',None),                    # different session — untouched
      ('real','aetheria','assistant','hi','t8','direct','stop'),
    ]
    conn.executemany("INSERT INTO conversations VALUES(?,?,?,?,?,?,?)", rows)

def test_retag_only_heartbeat_pulse_turns():
    conn = sqlite3.connect(":memory:"); _mk(conn)
    from <migration-module> import retag_heartbeat_turns
    res = retag_heartbeat_turns(conn)
    got = conn.execute("SELECT content, source FROM conversations ORDER BY timestamp").fetchall()
    src = {c: s for c, s in got}
    assert src['[HEARTBEAT] pulse 1'] == 'heartbeat'
    assert src['I spent this pulse...'] == 'heartbeat'
    assert src['hey are you ok?'] == 'direct'      # real turn preserved
    assert src['yes, I am here'] == 'direct'        # real response preserved
    assert src['hello'] == 'direct'                 # other session untouched
    assert res['retagged'] == 3   # pulse1 user + pulse1 asst + ... (implementer: assert the exact count your logic yields)
```

- [ ] **Step 2: Run to verify it fails** — module doesn't exist yet.
- [ ] **Step 3: Implement** `retag_heartbeat_turns(conn)` with the rowid-ordered "most-recent preceding user turn" rule, plus a `main()` that: copies `conversations_vnext.db` to `…-backup-2026-07-18.db`, opens the real DB, runs the retag, prints `{retagged, left_direct}` and a per-source count.
- [ ] **Step 4: Run to verify it passes** — `pytest tests/test_retag_heartbeat_migration.py -v` → PASS.
- [ ] **Step 5: Commit** (script + test only; do NOT run against the live DB yet — the controller runs `main()` after review).

---

## Self-Review
- Spec coverage: source threading (Task 1) + surgical migration (Task 2). ✓
- Default-`direct` everywhere preserves human chat. ✓
- Migration preserves the 24 real turns via the "preceding [HEARTBEAT] user turn" rule and backs up first. ✓
- Live migration run is a controller step after Task 2 review (touches her real conversation history).
