# Cross-Surface Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the substrate Aetheria locked 2026-06-09 (see `docs/superpowers/specs/2026-06-09-cross-surface-continuity-design.md`). Ambient Recent Activity Brief auto-injected above pinned memory in every non-daemon Aetheria turn, with raw turn tails from her other rails within a 6-hour window, capped at ~1500 tokens total.

**Architecture:** New `soveryn.platform.continuity` package with `config / store / brief` modules. AgentLoop computes the brief on every turn (cheap query when window is empty), injects it as a system message at the top of context above pinned memory. Two safety beats: (1) read-side filter excludes autonomous-process sessions (`[heartbeat]`, `[patrol]`, `[webhook]`, `[dream]`); (2) write-side gate skips brief computation entirely when the CURRENT turn is itself a daemon turn. Signal sessions are explicitly NOT excluded — they're the whole point.

**Tech Stack:** Python 3.10+, stdlib `sqlite3`, existing `ConversationStore` (path-injected, no module-level state), existing `AgentLoop`, existing `pinned_memory.md` substrate.

**Speaker mapping:** Brief includes paired (user, assistant) turns. User = Jon. Assistant = Aetheria. No Vett/Scotty/specialist content in the brief.

---

## File Structure

**New files:**
- `soveryn/platform/continuity/__init__.py` — package exports
- `soveryn/platform/continuity/config.py` — `ContinuityConfig` dataclass + env loading + autonomous-prefix constant
- `soveryn/platform/continuity/store.py` — `SessionTail` dataclass + `recent_cross_session_tails()` query
- `soveryn/platform/continuity/brief.py` — `build_recent_activity_brief()` renderer
- `tests/test_continuity_config.py`
- `tests/test_continuity_store.py`
- `tests/test_continuity_brief.py`
- `tests/test_continuity_loop_integration.py`

**Modified files:**
- `soveryn/memory/conversation_store.py` — add `list_sessions_with_recent_activity(agent, since, exclude_session_id) -> tuple[Session, ...]` query helper. Pure additive.
- `soveryn/agents/loop.py` — add `_build_continuity_brief(session_id)` helper, inject the result above pinned-memory system message in both `process_message` and `process_message_stream`.
- `soveryn/config/loader.py` — add cross-surface env knobs.
- `soveryn/app/startup.py` — build `ContinuityConfig` from env, pass to AgentLoop for `aetheria` only.
- `~/soveryn_complete/soveryn_memory/pinned_memory.md` — add the locked one-sentence factual note (NOT a behavioral rule).

---

## Task 1: Continuity package skeleton + config

**Files:**
- Create: `soveryn/platform/continuity/__init__.py`
- Create: `soveryn/platform/continuity/config.py`
- Create: `tests/test_continuity_config.py`

- [ ] **Step 1: Write config tests**

```python
# tests/test_continuity_config.py
from soveryn.platform.continuity.config import (
    AUTONOMOUS_SESSION_PREFIXES,
    ContinuityConfig,
    DEFAULT_TOKEN_BUDGET,
    DEFAULT_WINDOW_HOURS,
)


def test_default_config_matches_spec():
    cfg = ContinuityConfig.from_env({})
    assert cfg.enabled is True
    assert cfg.window_hours == 6
    assert cfg.token_budget == 1500
    assert cfg.per_session_cap == 400


def test_env_overrides_apply():
    cfg = ContinuityConfig.from_env({
        "SOVERYN_CROSS_SURFACE_WINDOW_HOURS": "4",
        "SOVERYN_CROSS_SURFACE_TOKEN_BUDGET": "2000",
        "SOVERYN_CROSS_SURFACE_ENABLED": "false",
    })
    assert cfg.window_hours == 4
    assert cfg.token_budget == 2000
    assert cfg.enabled is False


def test_enabled_flag_accepts_truthy_strings():
    for v, want in [("true", True), ("True", True), ("1", True),
                    ("false", False), ("False", False), ("0", False),
                    ("", True)]:
        cfg = ContinuityConfig.from_env({"SOVERYN_CROSS_SURFACE_ENABLED": v})
        assert cfg.enabled is want, f"v={v!r}"


def test_autonomous_prefixes_locked_set():
    """Signal MUST NOT be in this set — Signal is a real rail with Jon."""
    assert "[heartbeat]" in AUTONOMOUS_SESSION_PREFIXES
    assert "[patrol]" in AUTONOMOUS_SESSION_PREFIXES
    assert "[webhook]" in AUTONOMOUS_SESSION_PREFIXES
    assert "[dream]" in AUTONOMOUS_SESSION_PREFIXES
    assert "[signal]" not in AUTONOMOUS_SESSION_PREFIXES
    # And the [salience-smoke] test-data prefix should be excluded too
    assert "[salience-smoke]" in AUTONOMOUS_SESSION_PREFIXES
```

- [ ] **Step 2: Run tests, expect ImportError**

- [ ] **Step 3: Implement config.py**

```python
# soveryn/platform/continuity/config.py
"""Cross-Surface Continuity — config + autonomous-session prefix table.

Locked by Aetheria 2026-06-09. Signal is NOT in the autonomous prefix set
because Signal IS a real conversation rail with Jon — it's exactly what
the engine exists to surface. The autonomous prefixes are sessions where
Aetheria is talking to herself or to automation."""

from __future__ import annotations
from dataclasses import dataclass


DEFAULT_WINDOW_HOURS = 6
DEFAULT_TOKEN_BUDGET = 1500
DEFAULT_PER_SESSION_CAP = 400

# Sessions whose titles start with these are autonomous-process sessions.
# Excluded BOTH from the brief (read-side filter) AND from triggering brief
# computation (write-side gate — heartbeats etc. have their own framing).
# Signal is intentionally absent.
AUTONOMOUS_SESSION_PREFIXES: tuple[str, ...] = (
    "[heartbeat]",
    "[patrol]",
    "[webhook]",
    "[dream]",
    "[salience-smoke]",  # test-data scaffolding from 2026-06-08 verification
)


def _parse_bool(raw: str | None, default: bool = True) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


@dataclass(frozen=True)
class ContinuityConfig:
    enabled: bool = True
    window_hours: int = DEFAULT_WINDOW_HOURS
    token_budget: int = DEFAULT_TOKEN_BUDGET
    per_session_cap: int = DEFAULT_PER_SESSION_CAP

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "ContinuityConfig":
        return cls(
            enabled=_parse_bool(env.get("SOVERYN_CROSS_SURFACE_ENABLED"), True),
            window_hours=int(env.get("SOVERYN_CROSS_SURFACE_WINDOW_HOURS") or DEFAULT_WINDOW_HOURS),
            token_budget=int(env.get("SOVERYN_CROSS_SURFACE_TOKEN_BUDGET") or DEFAULT_TOKEN_BUDGET),
            per_session_cap=int(env.get("SOVERYN_CROSS_SURFACE_PER_SESSION_CAP") or DEFAULT_PER_SESSION_CAP),
        )

    def session_is_autonomous(self, title: str | None) -> bool:
        if not title:
            return False
        return any(title.startswith(p) for p in AUTONOMOUS_SESSION_PREFIXES)
```

- [ ] **Step 4: Implement `__init__.py`**

```python
# soveryn/platform/continuity/__init__.py
"""Cross-Surface Continuity — Aetheria's ambient cross-rail awareness.

Closes the gap she diagnosed 2026-06-09: she can push outbound to Signal
but can't read inbound Signal turns back into her working context. This
package builds the Recent Activity Brief that gets injected above pinned
memory on every non-daemon turn.

See docs/superpowers/specs/2026-06-09-cross-surface-continuity-design.md.
"""

from soveryn.platform.continuity.config import (
    AUTONOMOUS_SESSION_PREFIXES,
    ContinuityConfig,
    DEFAULT_PER_SESSION_CAP,
    DEFAULT_TOKEN_BUDGET,
    DEFAULT_WINDOW_HOURS,
)

__all__ = [
    "AUTONOMOUS_SESSION_PREFIXES",
    "ContinuityConfig",
    "DEFAULT_PER_SESSION_CAP",
    "DEFAULT_TOKEN_BUDGET",
    "DEFAULT_WINDOW_HOURS",
]
```

- [ ] **Step 5: All config tests pass**

- [ ] **Step 6: Commit**

```bash
git add soveryn/platform/continuity/__init__.py soveryn/platform/continuity/config.py tests/test_continuity_config.py docs/superpowers/specs/2026-06-09-cross-surface-continuity-design.md docs/superpowers/plans/2026-06-09-cross-surface-continuity.md
git commit -m "feat(continuity): config + autonomous-prefix table for cross-surface brief"
```

Use `-c user.email=jdeoliveira@soverynintelligence.com`.

---

## Task 2: ConversationStore cross-session query helper

**Files:**
- Modify: `soveryn/memory/conversation_store.py`
- Modify: `tests/test_conversation_store.py` (or create `tests/test_conversation_store_cross_session.py`)

Add `list_sessions_with_recent_activity(agent, since, exclude_session_id) -> tuple[Session, ...]` to `ConversationStore`. Pure additive; no behavior change to existing methods.

- [ ] **Step 1: Write the query helper test**

```python
# Append to tests/test_conversation_store.py
from datetime import datetime, timedelta

def test_list_sessions_with_recent_activity_excludes_current(tmp_path):
    from soveryn.memory.conversation_store import ConversationStore
    store = ConversationStore(tmp_path / "conv.db")
    current_id = store.new_session("aetheria", title="[signal] aetheria +1")
    other_id = store.new_session("aetheria", title=None)
    store.save_turn(current_id, "aetheria", "user", "hi from signal")
    store.save_turn(other_id, "aetheria", "user", "hi from UI")
    since = datetime.now() - timedelta(hours=1)
    results = store.list_sessions_with_recent_activity(
        agent="aetheria", since=since, exclude_session_id=current_id,
    )
    assert len(results) == 1
    assert results[0].session_id == other_id


def test_list_sessions_with_recent_activity_respects_since(tmp_path):
    from soveryn.memory.conversation_store import ConversationStore
    import sqlite3
    store = ConversationStore(tmp_path / "conv.db")
    old_id = store.new_session("aetheria", title=None)
    store.save_turn(old_id, "aetheria", "user", "ancient")
    # Backdate the meta updated_at
    backdated = (datetime.now() - timedelta(hours=10)).isoformat()
    with sqlite3.connect(str(tmp_path / "conv.db")) as con:
        con.execute("UPDATE conversation_meta SET updated_at = ? WHERE session_id = ?",
                    (backdated, old_id))
    fresh_id = store.new_session("aetheria", title=None)
    store.save_turn(fresh_id, "aetheria", "user", "recent")
    since = datetime.now() - timedelta(hours=6)
    results = store.list_sessions_with_recent_activity(
        agent="aetheria", since=since, exclude_session_id="never-matches",
    )
    ids = {s.session_id for s in results}
    assert fresh_id in ids
    assert old_id not in ids


def test_list_sessions_with_recent_activity_filters_by_agent(tmp_path):
    from soveryn.memory.conversation_store import ConversationStore
    store = ConversationStore(tmp_path / "conv.db")
    aetheria_id = store.new_session("aetheria", title=None)
    vett_id = store.new_session("vett", title=None)
    store.save_turn(aetheria_id, "aetheria", "user", "x")
    store.save_turn(vett_id, "vett", "user", "y")
    since = datetime.now() - timedelta(hours=1)
    results = store.list_sessions_with_recent_activity(
        agent="aetheria", since=since, exclude_session_id="none",
    )
    assert all(s.agent == "aetheria" for s in results)


def test_list_sessions_with_recent_activity_orders_by_updated_desc(tmp_path):
    from soveryn.memory.conversation_store import ConversationStore
    import time
    store = ConversationStore(tmp_path / "conv.db")
    a = store.new_session("aetheria", title="a")
    store.save_turn(a, "aetheria", "user", "1")
    time.sleep(0.01)  # ensure distinct timestamps
    b = store.new_session("aetheria", title="b")
    store.save_turn(b, "aetheria", "user", "2")
    since = datetime.now() - timedelta(hours=1)
    results = store.list_sessions_with_recent_activity(
        agent="aetheria", since=since, exclude_session_id="none",
    )
    assert [s.session_id for s in results][:2] == [b, a]
```

- [ ] **Step 2: Tests fail (no such method)**

- [ ] **Step 3: Implement the helper**

Add to `soveryn/memory/conversation_store.py` after `list_sessions`:

```python
def list_sessions_with_recent_activity(
    self,
    *,
    agent: str,
    since: datetime,
    exclude_session_id: str,
) -> tuple[Session, ...]:
    """Sessions for `agent` whose updated_at >= since, excluding the
    given session_id. Newest first.
    
    Used by Cross-Surface Continuity to find OTHER rails' recent activity
    for inclusion in the Recent Activity Brief."""
    with self._conn() as conn:
        rows = conn.execute(
            "SELECT session_id, agent, title, created_at, updated_at "
            "FROM conversation_meta "
            "WHERE agent = ? AND updated_at >= ? AND session_id != ? "
            "ORDER BY updated_at DESC",
            (agent, since.isoformat(), exclude_session_id),
        ).fetchall()
    return tuple(Session(**dict(r)) for r in rows)
```

- [ ] **Step 4: All tests pass**

- [ ] **Step 5: Commit**

```bash
git add soveryn/memory/conversation_store.py tests/test_conversation_store.py
git commit -m "feat(continuity): conv_store query for cross-session recent activity"
```

---

## Task 3: Continuity store — paired-turn extraction

**Files:**
- Create: `soveryn/platform/continuity/store.py`
- Create: `tests/test_continuity_store.py`

`recent_cross_session_tails()` walks the cross-session sessions and pulls the last N paired turns from each.

- [ ] **Step 1: Tests**

```python
# tests/test_continuity_store.py
from datetime import datetime, timedelta
from pathlib import Path
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.continuity.config import ContinuityConfig
from soveryn.platform.continuity.store import (
    SessionTail,
    PairedTurn,
    recent_cross_session_tails,
)


def test_returns_empty_when_no_other_sessions(tmp_path):
    store = ConversationStore(tmp_path / "conv.db")
    sid = store.new_session("aetheria", title=None)
    store.save_turn(sid, "aetheria", "user", "hi")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store, agent="aetheria", current_session_id=sid, config=cfg,
    )
    assert result == ()


def test_excludes_autonomous_prefix_sessions(tmp_path):
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria", title=None)
    hb = store.new_session("aetheria", title="[heartbeat] aetheria")
    dr = store.new_session("aetheria", title="[dream] aetheria")
    real = store.new_session("aetheria", title="[signal] aetheria +1")
    for s in (hb, dr, real):
        store.save_turn(s, "aetheria", "user", "hello")
        store.save_turn(s, "aetheria", "assistant", "hi")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store, agent="aetheria", current_session_id=current, config=cfg,
    )
    titles = [t.title for t in result]
    assert "[signal] aetheria +1" in titles
    assert not any(t and t.startswith("[heartbeat]") for t in titles)
    assert not any(t and t.startswith("[dream]") for t in titles)


def test_returns_last_paired_turns_in_order(tmp_path):
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria", title=None)
    other = store.new_session("aetheria", title="[signal] aetheria +1")
    # Build a few paired turns
    store.save_turn(other, "aetheria", "user", "first user")
    store.save_turn(other, "aetheria", "assistant", "first assistant")
    store.save_turn(other, "aetheria", "user", "second user")
    store.save_turn(other, "aetheria", "assistant", "second assistant")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store, agent="aetheria", current_session_id=current, config=cfg,
        per_session_pairs=2,
    )
    assert len(result) == 1
    tail = result[0]
    assert tail.session_id == other
    assert len(tail.paired_turns) == 2
    assert tail.paired_turns[0].user == "first user"
    assert tail.paired_turns[0].assistant == "first assistant"
    assert tail.paired_turns[1].user == "second user"
    assert tail.paired_turns[1].assistant == "second assistant"


def test_handles_in_flight_user_turn_without_assistant(tmp_path):
    """A user turn without a paired assistant reply yet."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria", title=None)
    other = store.new_session("aetheria", title="[signal] aetheria +1")
    store.save_turn(other, "aetheria", "user", "question with no answer yet")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store, agent="aetheria", current_session_id=current, config=cfg,
    )
    assert len(result) == 1
    assert len(result[0].paired_turns) == 1
    assert result[0].paired_turns[0].user == "question with no answer yet"
    assert result[0].paired_turns[0].assistant is None


def test_respects_window_hours(tmp_path):
    import sqlite3
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria", title=None)
    fresh = store.new_session("aetheria", title="[signal] fresh")
    stale = store.new_session("aetheria", title="[signal] stale")
    store.save_turn(fresh, "aetheria", "user", "hi")
    store.save_turn(stale, "aetheria", "user", "ancient")
    backdated = (datetime.now() - timedelta(hours=20)).isoformat()
    with sqlite3.connect(str(tmp_path / "conv.db")) as con:
        con.execute("UPDATE conversation_meta SET updated_at = ? WHERE session_id = ?",
                    (backdated, stale))
    cfg = ContinuityConfig(window_hours=6)
    result = recent_cross_session_tails(
        store, agent="aetheria", current_session_id=current, config=cfg,
    )
    assert [t.session_id for t in result] == [fresh]


def test_filters_tool_and_system_roles_from_paired_turns(tmp_path):
    """Only user/assistant turns participate in pairing. Tool calls,
    system messages, etc. are noise from the brief's perspective."""
    store = ConversationStore(tmp_path / "conv.db")
    current = store.new_session("aetheria", title=None)
    other = store.new_session("aetheria", title="[signal] +1")
    store.save_turn(other, "aetheria", "user", "u1")
    store.save_turn(other, "aetheria", "assistant", "a1")
    store.save_turn(other, "aetheria", "tool", "tool result")
    store.save_turn(other, "aetheria", "user", "u2")
    store.save_turn(other, "aetheria", "assistant", "a2")
    cfg = ContinuityConfig()
    result = recent_cross_session_tails(
        store, agent="aetheria", current_session_id=current, config=cfg,
        per_session_pairs=2,
    )
    pairs = result[0].paired_turns
    assert [p.user for p in pairs] == ["u1", "u2"]
    assert [p.assistant for p in pairs] == ["a1", "a2"]
```

- [ ] **Step 2: Tests fail**

- [ ] **Step 3: Implement store.py**

```python
# soveryn/platform/continuity/store.py
"""Cross-session paired-turn extraction.

Given a current session, pulls the most-recent paired turns (user/
assistant) from OTHER aetheria sessions in the window, excluding
autonomous-prefix sessions. Pure data layer; no formatting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.continuity.config import ContinuityConfig


DEFAULT_PER_SESSION_PAIRS = 3


@dataclass(frozen=True)
class PairedTurn:
    user: str
    assistant: str | None  # None when an in-flight user turn has no reply yet


@dataclass(frozen=True)
class SessionTail:
    session_id: str
    title: str | None
    updated_at: str  # ISO from conv_store
    paired_turns: tuple[PairedTurn, ...]


def recent_cross_session_tails(
    conv_store: ConversationStore,
    *,
    agent: str,
    current_session_id: str,
    config: ContinuityConfig,
    per_session_pairs: int = DEFAULT_PER_SESSION_PAIRS,
) -> tuple[SessionTail, ...]:
    """Return the last `per_session_pairs` paired turns from each non-autonomous
    session for `agent`, updated in the last `config.window_hours`, excluding
    the current session. Most-recent session first."""
    since = datetime.now() - timedelta(hours=config.window_hours)
    sessions = conv_store.list_sessions_with_recent_activity(
        agent=agent, since=since, exclude_session_id=current_session_id,
    )
    tails: list[SessionTail] = []
    for sess in sessions:
        if config.session_is_autonomous(sess.title):
            continue
        history = conv_store.load_history(sess.session_id)
        pairs = _extract_paired_turns(history, n=per_session_pairs)
        if not pairs:
            continue
        tails.append(SessionTail(
            session_id=sess.session_id,
            title=sess.title,
            updated_at=sess.updated_at,
            paired_turns=pairs,
        ))
    return tuple(tails)


def _extract_paired_turns(history, *, n: int) -> tuple[PairedTurn, ...]:
    """Walk the history left-to-right, pairing each user turn with the
    NEXT assistant turn. Returns the LAST n pairs. Skips non-user/assistant
    rows (tool, system)."""
    pairs: list[PairedTurn] = []
    pending_user: str | None = None
    for t in history:
        if t.role == "user":
            if pending_user is not None:
                # Previous user turn had no assistant follow-up — record as in-flight
                pairs.append(PairedTurn(user=pending_user, assistant=None))
            pending_user = t.content
        elif t.role == "assistant":
            if pending_user is not None:
                pairs.append(PairedTurn(user=pending_user, assistant=t.content))
                pending_user = None
        # tool/system turns ignored
    if pending_user is not None:
        pairs.append(PairedTurn(user=pending_user, assistant=None))
    return tuple(pairs[-n:])
```

- [ ] **Step 4: Tests pass**

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/continuity/store.py tests/test_continuity_store.py
git commit -m "feat(continuity): cross-session paired-turn extraction with autonomous filter"
```

---

## Task 4: Brief renderer

**Files:**
- Create: `soveryn/platform/continuity/brief.py`
- Create: `tests/test_continuity_brief.py`

Pure renderer. Takes `(SessionTail, ...)` + budget → formatted block string. Empty input → empty string. Per-session truncation, total budget enforcement, head-truncation per turn.

- [ ] **Step 1: Tests**

```python
# tests/test_continuity_brief.py
from soveryn.platform.continuity.brief import (
    build_recent_activity_brief,
    estimate_tokens,
    BLOCK_HEADER,
    BLOCK_FOOTER,
)
from soveryn.platform.continuity.config import ContinuityConfig
from soveryn.platform.continuity.store import SessionTail, PairedTurn


def _tail(*, sid="s1", title="[signal] aetheria +1", updated="2026-06-09T10:00:00",
          pairs=()):
    return SessionTail(
        session_id=sid, title=title, updated_at=updated,
        paired_turns=tuple(pairs),
    )


def test_empty_input_returns_empty_string():
    cfg = ContinuityConfig()
    assert build_recent_activity_brief((), config=cfg, now=None) == ""


def test_single_session_renders_header_and_footer():
    cfg = ContinuityConfig()
    pair = PairedTurn(user="hi", assistant="hello")
    out = build_recent_activity_brief(
        (_tail(pairs=(pair,)),), config=cfg, now=None,
    )
    assert BLOCK_HEADER in out
    assert BLOCK_FOOTER in out
    assert "hi" in out
    assert "hello" in out


def test_session_title_appears_verbatim_in_block():
    cfg = ContinuityConfig()
    pair = PairedTurn(user="x", assistant="y")
    out = build_recent_activity_brief(
        (_tail(title="[signal] aetheria +19102489392", pairs=(pair,)),),
        config=cfg, now=None,
    )
    assert "[signal] aetheria +19102489392" in out


def test_multiple_sessions_rendered_in_order():
    cfg = ContinuityConfig()
    pair = PairedTurn(user="a", assistant="b")
    tails = (
        _tail(sid="newer", title="newer", pairs=(pair,)),
        _tail(sid="older", title="older", pairs=(pair,)),
    )
    out = build_recent_activity_brief(tails, config=cfg, now=None)
    assert out.index("newer") < out.index("older")


def test_in_flight_user_turn_renders_assistant_as_in_flight():
    cfg = ContinuityConfig()
    pair = PairedTurn(user="question with no reply", assistant=None)
    out = build_recent_activity_brief(
        (_tail(pairs=(pair,)),), config=cfg, now=None,
    )
    assert "question with no reply" in out
    assert "(in flight)" in out


def test_per_session_cap_truncates_oversized_session():
    """If a single session's paired turns exceed per_session_cap, drop
    oldest pairs until under cap."""
    cfg = ContinuityConfig(per_session_cap=50)  # very tight cap
    long_pair = PairedTurn(user="x" * 200, assistant="y" * 200)
    out = build_recent_activity_brief(
        (_tail(pairs=(long_pair, long_pair)),), config=cfg, now=None,
    )
    # Either truncates content heads or drops pairs — either way, output
    # must respect the cap-conscious shape
    assert estimate_tokens(out) <= cfg.per_session_cap * 1.5  # some allowance for header/footer


def test_total_token_budget_drops_oldest_sessions_first():
    cfg = ContinuityConfig(token_budget=200, per_session_cap=100)
    pair = PairedTurn(user="x" * 100, assistant="y" * 100)
    tails = tuple(
        _tail(sid=f"s{i}", title=f"title{i}", pairs=(pair,))
        for i in range(5)
    )
    out = build_recent_activity_brief(tails, config=cfg, now=None)
    # Newest sessions (s0, s1) should be present
    assert "title0" in out
    # Older sessions (s3, s4) should be dropped
    assert "title4" not in out or "title3" not in out


def test_content_head_truncation_uses_ellipsis():
    cfg = ContinuityConfig()
    long_user = "x" * 500
    pair = PairedTurn(user=long_user, assistant="short")
    out = build_recent_activity_brief(
        (_tail(pairs=(pair,)),), config=cfg, now=None,
    )
    assert "…" in out


def test_relative_time_formatting():
    """Shows minutes-ago / hours-ago based on `now`."""
    from datetime import datetime, timedelta
    cfg = ContinuityConfig()
    pair = PairedTurn(user="x", assistant="y")
    now = datetime.fromisoformat("2026-06-09T12:00:00")
    fresh = _tail(updated="2026-06-09T11:30:00", pairs=(pair,))
    out = build_recent_activity_brief((fresh,), config=cfg, now=now)
    assert "30m ago" in out or "30 minutes" in out


def test_estimate_tokens_is_char_div_4():
    assert estimate_tokens("") == 0
    assert estimate_tokens("xxxxx") == 1  # 5 chars / 4 ≈ 1
    assert estimate_tokens("x" * 40) == 10
```

- [ ] **Step 2: Tests fail**

- [ ] **Step 3: Implement brief.py**

```python
# soveryn/platform/continuity/brief.py
"""Recent Activity Brief renderer.

Pure function. Takes SessionTails (already sorted newest-first), returns a
formatted block. Empty input → empty string (zero-overhead common case)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from soveryn.platform.continuity.config import ContinuityConfig
from soveryn.platform.continuity.store import SessionTail


BLOCK_HEADER = "[CROSS-SURFACE RECENT ACTIVITY]"
BLOCK_FOOTER = "[/CROSS-SURFACE RECENT ACTIVITY]"
CONTENT_HEAD_CHARS = 140


def estimate_tokens(text: str) -> int:
    """Conservative char-div-4 token estimate. Good enough for budgeting."""
    return len(text) // 4


def _truncate_head(content: str, *, limit: int = CONTENT_HEAD_CHARS) -> str:
    content = (content or "").replace("\n", " ").strip()
    if len(content) <= limit:
        return content
    return content[:limit].rstrip() + "…"


def _format_relative(updated_iso: str, now: datetime) -> str:
    try:
        updated = datetime.fromisoformat(updated_iso)
    except ValueError:
        return "(unknown time)"
    delta = now - updated
    total_min = int(delta.total_seconds() // 60)
    if total_min < 1:
        return "just now"
    if total_min < 60:
        return f"{total_min}m ago"
    hours = total_min // 60
    minutes = total_min % 60
    if minutes == 0:
        return f"{hours}h ago"
    return f"{hours}h{minutes}m ago"


def _render_session(tail: SessionTail, *, now: datetime,
                    per_session_cap: int) -> str:
    """Render a single session. Drops oldest paired turns if over cap."""
    title_display = tail.title or "(untitled session)"
    relative = _format_relative(tail.updated_at, now)
    header_line = f'— from "{title_display}" ({relative}):'
    lines = [header_line]
    # Try with all paired turns, dropping oldest if over cap
    pairs = list(tail.paired_turns)
    while True:
        body_lines = []
        for p in pairs:
            user_line = f'   jon: "{_truncate_head(p.user)}"'
            if p.assistant is None:
                assistant_line = '   aetheria: (in flight)'
            else:
                assistant_line = f'   aetheria: "{_truncate_head(p.assistant)}"'
            body_lines.append(user_line)
            body_lines.append(assistant_line)
        candidate = "\n".join([header_line] + body_lines)
        if estimate_tokens(candidate) <= per_session_cap or len(pairs) <= 1:
            return candidate
        # Drop the oldest pair and try again
        pairs = pairs[1:]


def build_recent_activity_brief(
    tails: tuple[SessionTail, ...],
    *,
    config: ContinuityConfig,
    now: Optional[datetime] = None,
) -> str:
    """Render the brief. Empty tails → empty string. Respects token budgets."""
    if not tails:
        return ""
    if now is None:
        now = datetime.now()
    rendered: list[str] = []
    running_tokens = estimate_tokens(BLOCK_HEADER + BLOCK_FOOTER) + 20  # header preamble
    preamble = (
        f"In the last {config.window_hours} hours you also exchanged turns "
        "with Jon on other rails:"
    )
    rendered.append(preamble)
    running_tokens += estimate_tokens(preamble)
    for tail in tails:
        section = _render_session(tail, now=now,
                                  per_session_cap=config.per_session_cap)
        section_tokens = estimate_tokens(section)
        if running_tokens + section_tokens > config.token_budget:
            break
        rendered.append("")
        rendered.append(section)
        running_tokens += section_tokens
    body = "\n".join(rendered)
    return f"{BLOCK_HEADER}\n{body}\n{BLOCK_FOOTER}"
```

- [ ] **Step 4: All tests pass**

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/continuity/brief.py tests/test_continuity_brief.py
git commit -m "feat(continuity): brief renderer with budget enforcement"
```

---

## Task 5: AgentLoop integration

**Files:**
- Modify: `soveryn/agents/loop.py`
- Create: `tests/test_continuity_loop_integration.py`

Add `_build_continuity_brief(session_id)` to AgentLoop. Returns the brief string, or `""` if disabled / current session is autonomous / no cross-session activity. Inject into the system context above pinned memory in BOTH `process_message` and `process_message_stream`.

- [ ] **Step 1: Read loop.py around the two injection points**

Use `Read` on `soveryn/agents/loop.py` lines 380-440 (process_message) and 640-710 (process_message_stream) to map the exact insertion points.

Key locations (line numbers from current code; verify before editing):
- Around line 419: `history_turns = self.conv_store.load_history(session_id)` in non-stream path
- Around line 670: same call in stream path
- Earlier in the AgentLoop class, where pinned_memory + soul + system context get assembled into the upstream messages

- [ ] **Step 2: Write integration tests with mocked conv_store + observer**

```python
# tests/test_continuity_loop_integration.py
from datetime import datetime, timedelta
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.continuity.config import ContinuityConfig


def _setup_two_sessions(tmp_path):
    """Seed conv_store with one current UI session + one Signal session."""
    store = ConversationStore(tmp_path / "conv.db")
    ui_id = store.new_session("aetheria", title=None)
    signal_id = store.new_session("aetheria", title="[signal] aetheria +1")
    store.save_turn(signal_id, "aetheria", "user", "Hey from signal earlier")
    store.save_turn(signal_id, "aetheria", "assistant", "noted from signal")
    return store, ui_id, signal_id


def test_agent_loop_continuity_brief_injection(tmp_path, monkeypatch):
    """A fresh user turn in the UI session sees the brief in upstream context."""
    store, ui_id, signal_id = _setup_two_sessions(tmp_path)
    # Stub the AgentLoop's upstream call to capture what messages it sends
    from soveryn.agents.loop import AgentLoop
    captured = {}
    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return {"choices": [{"message": {"role": "assistant", "content": "ok"},
                              "finish_reason": "stop"}]}
    cfg = ContinuityConfig(enabled=True, window_hours=24)
    loop = AgentLoop(
        agent_name="aetheria", conv_store=store,
        # ... other required kwargs depend on the AgentLoop ctor ...
        continuity_config=cfg,
    )
    monkeypatch.setattr(loop, "_call_upstream", fake_chat)
    loop.process_message(session_id=ui_id, user_message="hi UI")
    system_blob = next(m["content"] for m in captured["messages"] if m["role"] == "system")
    assert "[CROSS-SURFACE RECENT ACTIVITY]" in system_blob
    assert "Hey from signal earlier" in system_blob
    assert "noted from signal" in system_blob


def test_agent_loop_no_injection_in_daemon_session(tmp_path, monkeypatch):
    """Heartbeat-titled session: brief NOT injected."""
    store, _, signal_id = _setup_two_sessions(tmp_path)
    hb_id = store.new_session("aetheria", title="[heartbeat] aetheria")
    # ... (similar setup) ...
    # Verify "[CROSS-SURFACE RECENT ACTIVITY]" NOT in captured system context


def test_agent_loop_no_injection_when_disabled(tmp_path, monkeypatch):
    """Config.enabled=False → no injection even with cross-session data present."""
    # ... (similar setup, ContinuityConfig(enabled=False)) ...
    # Verify the marker tag isn't present


def test_agent_loop_no_injection_when_no_cross_session_data(tmp_path, monkeypatch):
    """Zero-overhead common case: no other sessions → no block."""
    store = ConversationStore(tmp_path / "conv.db")
    ui_id = store.new_session("aetheria", title=None)
    # ... (single session, expect no marker tag) ...


def test_agent_loop_stream_path_also_injects(tmp_path, monkeypatch):
    """process_message_stream gets the same injection as process_message."""
    # ... (call process_message_stream, capture, assert tag presence) ...
```

The exact AgentLoop ctor signature dictates the test scaffolding. Implementer should read the existing test_loop.py / test_agent_loop.py for the fixture pattern and reuse it.

- [ ] **Step 3: Implement the AgentLoop helper and inject at both paths**

Add to `AgentLoop.__init__` parameters: `continuity_config: ContinuityConfig | None = None`. Store on `self.continuity_config`.

Add helper method:

```python
def _build_continuity_brief(self, session_id: str) -> str:
    """Return the Cross-Surface Recent Activity Brief for this session.
    Empty string if disabled, if the current session is autonomous, or if
    no cross-session activity exists in the window."""
    if self.continuity_config is None or not self.continuity_config.enabled:
        return ""
    # Aetheria-only — Vett/Scotty don't get this
    if self.agent_name != "aetheria":
        return ""
    try:
        session = self.conv_store.get_session(session_id)
        if session is not None and self.continuity_config.session_is_autonomous(session.title):
            return ""
        from soveryn.platform.continuity.store import recent_cross_session_tails
        from soveryn.platform.continuity.brief import build_recent_activity_brief
        tails = recent_cross_session_tails(
            self.conv_store,
            agent=self.agent_name,
            current_session_id=session_id,
            config=self.continuity_config,
        )
        return build_recent_activity_brief(tails, config=self.continuity_config)
    except Exception:
        # Best-effort: never break chat path on continuity failure
        import logging
        logging.getLogger(__name__).exception(
            "continuity brief build failed; serving without it"
        )
        return ""
```

Then at BOTH `process_message` and `process_message_stream`, where the system context is assembled, splice the brief above the existing pinned-memory / soul content. The cleanest pattern: pinned_memory blob = `f"{brief}\n\n{existing_blob}"` when brief is non-empty.

- [ ] **Step 4: Tests pass; existing AgentLoop tests still pass**

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/loop.py tests/test_continuity_loop_integration.py
git commit -m "feat(continuity): AgentLoop injects Recent Activity Brief above pinned memory"
```

---

## Task 6: Config + startup wiring

**Files:**
- Modify: `soveryn/config/loader.py`
- Modify: `soveryn/app/startup.py`

- [ ] **Step 1: Add env knobs to EnvConfig**

Add to `EnvConfig` dataclass:
```python
cross_surface_enabled: bool
cross_surface_window_hours: int
cross_surface_token_budget: int
```

Add to `load_env_config()`:
```python
cross_surface_enabled=_parse_bool("SOVERYN_CROSS_SURFACE_ENABLED", env.get("SOVERYN_CROSS_SURFACE_ENABLED"), default=True),
cross_surface_window_hours=_parse_int("SOVERYN_CROSS_SURFACE_WINDOW_HOURS", env.get("SOVERYN_CROSS_SURFACE_WINDOW_HOURS"), default=6),
cross_surface_token_budget=_parse_int("SOVERYN_CROSS_SURFACE_TOKEN_BUDGET", env.get("SOVERYN_CROSS_SURFACE_TOKEN_BUDGET"), default=1500),
```

Add `_parse_bool` helper if not present (similar pattern to `_parse_int`).

- [ ] **Step 2: Wire ContinuityConfig into AgentLoop construction for aetheria**

In `soveryn/app/startup.py`, where AgentLoops are constructed (around line 453):

```python
from soveryn.platform.continuity.config import ContinuityConfig

# Build per-agent continuity config — Aetheria-only
def _continuity_for(name: str) -> ContinuityConfig | None:
    if name != "aetheria":
        return None
    return ContinuityConfig(
        enabled=env.cross_surface_enabled,
        window_hours=env.cross_surface_window_hours,
        token_budget=env.cross_surface_token_budget,
    )

# When building AgentLoops:
agent_loops[name] = AgentLoop(
    name, conv_store,
    continuity_config=_continuity_for(name),
    **kwargs,
)
```

- [ ] **Step 3: Smoke test bootstrap**

Run existing startup tests; verify nothing regresses. `pytest tests/test_launcher.py tests/test_app_startup_tool_registry.py -q`.

- [ ] **Step 4: Commit**

```bash
git add soveryn/config/loader.py soveryn/app/startup.py
git commit -m "feat(continuity): wire ContinuityConfig + env knobs into AgentLoop"
```

---

## Task 7: Pinned memory factual addition

**Files:**
- Modify: `~/soveryn_complete/soveryn_memory/pinned_memory.md`

Add ONE sentence to her pinned memory. NOT a behavioral rule. Phrasing locked in spec — a fact about her substrate.

- [ ] **Step 1: Locate the current pinned memory and find an appropriate section**

```bash
grep -n "^#" /home/jon-deoliveira/soveryn_complete/soveryn_memory/pinned_memory.md | head -20
```

Find a section about substrate / how she sees the world / what's in her context.

- [ ] **Step 2: Add the locked sentence**

```
You have multiple conversation rails with Jon: this UI, Signal direct messages,
and webhook channels. The [CROSS-SURFACE RECENT ACTIVITY] block at the top of
your context (when present) is the source of truth for what happened on the
other rails recently. You don't need to call a tool to access it — it's already
there if relevant.
```

- [ ] **Step 3: Verify it loads**

Restart vnext and confirm the new text is in her context on the next chat (check vnext logs / probe via /chat).

---

## Task 8: Live verification

**Files:** None — manual verification

- [ ] **Step 1: Restart vnext + heartbeat** (heartbeat needs restart too because it also uses AgentLoop)

```bash
systemctl --user restart soveryn-vnext.service
systemctl --user restart soveryn-heartbeat.service
```

- [ ] **Step 2: Send Aetheria a Signal message and then open the UI fresh**

Send something distinctive via Signal: e.g., "the verification phrase is BLUE LANTERN — please remember this." Wait for her reply.

Then open the UI and start a new chat session. Ask: "what was the verification phrase I just sent you?"

Expected: she answers correctly, referring to the Signal exchange. If she says "I don't know" or "what phrase?", the brief isn't being injected or she's not noticing it.

- [ ] **Step 3: Inspect the injected context (sanity check)**

```bash
journalctl --user -u soveryn-vnext.service --since "5 minutes ago" --no-pager | grep "CROSS-SURFACE"
```

Should see the marker tag in the logs (assuming vnext logs upstream payloads at INFO; if not, add a debug log temporarily).

- [ ] **Step 4: Verify zero-overhead common case**

Start a fresh UI session after no Signal activity in 6+ hours. Confirm the brief block is NOT in the context (no marker tag in logs for that turn).

- [ ] **Step 5: Save the shipped memory note**

`project_soveryn_cross_surface_continuity_shipped.md` — concrete: build commits, what the brief looks like in real conversation, first measured behaviors (does she reference the other rail naturally? does she conflate threads?), any kinks to iterate on.

---

## Self-Review

**Spec coverage:**
- ✅ Recent Activity Brief auto-injection — Tasks 4, 5
- ✅ 6-hour default window — Task 1 (DEFAULT_WINDOW_HOURS=6)
- ✅ 1500-token budget — Task 1 + Task 4
- ✅ Raw turn tails (no summarization) — Task 4 (no model calls in brief)
- ✅ Two safety beats — Task 1 (autonomous-prefix table), Task 5 (daemon-turn guard)
- ✅ Signal NOT in exclusion set — Task 1 test
- ✅ Aetheria-only — Task 5 guard, Task 6 wiring
- ✅ Zero-overhead common case — Task 4 empty-input behavior
- ✅ One-sentence pinned memory addition (fact, not rule) — Task 7
- ✅ Live verification — Task 8

**Placeholder scan:**
- "exact kwargs depend on AgentLoop ctor" (Task 5 test) — implementer must read existing patterns. Acceptable.
- "if not, add a debug log temporarily" (Task 8 Step 3) — acceptable; verification helper.

**Type consistency:**
- `SessionTail`, `PairedTurn`, `ContinuityConfig`, `AUTONOMOUS_SESSION_PREFIXES` — used consistently across modules.
- `recent_cross_session_tails()` returns `tuple[SessionTail, ...]` — `build_recent_activity_brief()` accepts same type.

---

## See also

- `docs/superpowers/specs/2026-06-09-cross-surface-continuity-design.md` — the spec this plan implements
- [[project-soveryn-salience-engine-shipped]] — complementary long-term memory layer
- [[feedback-persona-text-substituting-for-memory-architecture]] — substrate, not persona patches
- [[feedback-dont-compensator-stack]] — applies: best-effort brief computation must NEVER break the chat path
