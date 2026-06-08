"""Tests for the specialist-spawning primitive (DSL Orchestration v1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from soveryn.agents.specialists import concurrency
from soveryn.agents.specialists.tools import (
    build_query_specialist_tool,
    build_spawn_specialist_tool,
    build_terminate_specialist_tool,
)
from soveryn.platform.tools.registry import ToolArgError


# ─── Test fixtures + helpers ────────────────────────────────────────────────


@pytest.fixture
def conv_db(tmp_path):
    """A conv_meta SQLite seeded with the production-shape schema. The
    specialist tools query/update this DB directly for concurrency + title."""
    db = tmp_path / "conv.db"
    with sqlite3.connect(str(db)) as con:
        con.execute("""
            CREATE TABLE conversation_meta (
                session_id TEXT PRIMARY KEY,
                agent TEXT NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
    return db


def _seed_session(db, *, session_id, agent, title):
    """Insert a row into conversation_meta for tests."""
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "INSERT INTO conversation_meta (session_id, agent, title, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, agent, title, "2026-06-07T00:00:00",
             "2026-06-07T00:00:00"),
        )


def _ok_poster_factory(content="ack", session_id="sess-new"):
    """Build a fake http_poster that responds OK to /sessions + /chat."""
    calls = []
    def poster(url, body, timeout):
        calls.append({"url": url, "body": body, "timeout": timeout})
        if url.endswith("/sessions"):
            return {
                "session_id": session_id, "agent": body["agent"],
                "title": body.get("title"),
            }
        return {
            "content": content, "session_id": session_id,
            "finish_reason": "stop",
        }
    return poster, calls


# ─── spawn_specialist ───────────────────────────────────────────────────────


def _spawn_args(**overrides):
    """Default valid args dict for spawn_specialist."""
    base = {
        "name": "kernel_analyst",
        "domain": "CUDA kernel optimization",
        "objective": "find the 2x speedup in the attention path",
        "interaction_mode": "researcher",
        "coord_node_id": "node-1",
        "target_agent": "vett",
        "initial_brief": "Read the attention kernel and report bottlenecks.",
    }
    base.update(overrides)
    return base


def test_spawn_specialist_mints_session_and_posts_invocation(conv_db):
    """The happy path: spawn creates a session, posts the framed invocation,
    returns specialist_id + first response."""
    poster, calls = _ok_poster_factory(
        content="Got it. Beginning analysis.",
        session_id="spec-sess-1",
    )
    tool = build_spawn_specialist_tool(
        conv_db_path=conv_db, http_poster=poster,
    )
    # Seed the spawn-side session as if /sessions actually wrote it
    _seed_session(
        conv_db, session_id="spec-sess-1", agent="vett",
        title="[specialist:kernel_analyst:node-1]",
    )
    result = tool.handler(_spawn_args())
    assert result["specialist_id"] == "spec-sess-1"
    assert result["name"] == "kernel_analyst"
    assert result["target_agent"] == "vett"
    assert result["coord_node_id"] == "node-1"
    assert "Beginning analysis" in result["first_response"]

    # Two POSTs: /sessions then /chat with the invocation framing.
    assert len(calls) == 2
    chat = calls[1]
    assert chat["url"].endswith("/chat")
    msg = chat["body"]["message"]
    assert "SPECIALIST INVOCATION FROM AETHERIA" in msg
    assert "kernel_analyst" in msg
    assert "CUDA kernel optimization" in msg
    assert "find the 2x speedup" in msg
    assert "coord:node-1" in msg
    assert "Read the attention kernel" in msg


def test_spawn_specialist_critic_mode_gets_critic_framing(conv_db):
    poster, calls = _ok_poster_factory()
    _seed_session(conv_db, session_id="sess-new", agent="vett",
                  title="[specialist:r:node-1]")
    tool = build_spawn_specialist_tool(conv_db_path=conv_db, http_poster=poster)
    tool.handler(_spawn_args(name="red_team", interaction_mode="critic"))
    msg = calls[1]["body"]["message"]
    assert "Interaction mode: critic" in msg
    assert "find flaws" in msg or "do not soften" in msg


def test_spawn_specialist_builder_mode_gets_builder_framing(conv_db):
    poster, calls = _ok_poster_factory()
    _seed_session(conv_db, session_id="sess-new", agent="vett",
                  title="[specialist:b:node-1]")
    tool = build_spawn_specialist_tool(conv_db_path=conv_db, http_poster=poster)
    tool.handler(_spawn_args(name="b", interaction_mode="builder"))
    msg = calls[1]["body"]["message"]
    assert "Interaction mode: builder" in msg
    assert "build the solution" in msg or "you are the specialist; act" in msg


def test_spawn_specialist_rejects_unknown_target_agent(conv_db):
    tool = build_spawn_specialist_tool(conv_db_path=conv_db)
    with pytest.raises(ToolArgError, match="target_agent"):
        tool.handler(_spawn_args(target_agent="aetheria"))


def test_spawn_specialist_rejects_unknown_interaction_mode(conv_db):
    tool = build_spawn_specialist_tool(conv_db_path=conv_db)
    with pytest.raises(ToolArgError, match="interaction_mode"):
        tool.handler(_spawn_args(interaction_mode="philosopher"))


def test_spawn_specialist_rejects_missing_coord_node_id(conv_db):
    tool = build_spawn_specialist_tool(conv_db_path=conv_db)
    with pytest.raises(ToolArgError, match="coord_node_id"):
        tool.handler(_spawn_args(coord_node_id=""))


def test_spawn_specialist_rejects_name_with_brackets(conv_db):
    """Name lands in the session title; brackets would break the title
    format the concurrency-counter relies on."""
    tool = build_spawn_specialist_tool(conv_db_path=conv_db)
    with pytest.raises(ToolArgError, match="name"):
        tool.handler(_spawn_args(name="bad[name]"))


def test_spawn_specialist_returns_concurrency_cap_error_when_at_cap(conv_db):
    """When 3 specialists are already active, spawn returns structured error."""
    # Seed three active specialist sessions
    for i in range(3):
        _seed_session(
            conv_db, session_id=f"sess-{i}", agent="vett",
            title=f"[specialist:s{i}:node-{i}]",
        )
    poster, _ = _ok_poster_factory()
    tool = build_spawn_specialist_tool(
        conv_db_path=conv_db, http_poster=poster,
    )
    result = tool.handler(_spawn_args(name="fourth"))
    assert result["error"] == "specialist_concurrency_cap"
    assert result["active_count"] == 3
    assert result["cap"] == 3


def test_spawn_specialist_archived_sessions_do_not_count_against_cap(conv_db):
    """Sessions retitled to '[specialist-archived:...]' free up cap room."""
    # 3 archived + 0 active = under cap
    for i in range(3):
        _seed_session(
            conv_db, session_id=f"arch-{i}", agent="vett",
            title=f"[specialist-archived:done{i}:node-{i}]",
        )
    poster, _ = _ok_poster_factory(session_id="new-spec")
    tool = build_spawn_specialist_tool(
        conv_db_path=conv_db, http_poster=poster,
    )
    # Should not return concurrency_cap error
    result = tool.handler(_spawn_args(name="fresh"))
    assert result.get("error") != "specialist_concurrency_cap"


# ─── query_specialist ───────────────────────────────────────────────────────


def test_query_specialist_sends_framed_message(conv_db):
    _seed_session(
        conv_db, session_id="spec-sess-1", agent="vett",
        title="[specialist:kernel_analyst:node-42]",
    )
    poster, calls = _ok_poster_factory(content="Observation: warp divergence")
    tool = build_query_specialist_tool(
        conv_db_path=conv_db, http_poster=poster,
    )
    result = tool.handler({
        "specialist_id": "spec-sess-1",
        "message": "What's the bottleneck in the softmax phase?",
    })
    assert result["response_content"] == "Observation: warp divergence"
    assert result["coord_node_id"] == "node-42"
    assert len(calls) == 1
    msg = calls[0]["body"]["message"]
    assert "SPECIALIST QUERY FROM AETHERIA" in msg
    assert "coord:node-42" in msg
    assert "softmax phase" in msg
    assert calls[0]["body"]["session_id"] == "spec-sess-1"
    assert calls[0]["body"]["agent"] == "vett"


def test_query_specialist_unknown_specialist_returns_structured_error(conv_db):
    tool = build_query_specialist_tool(conv_db_path=conv_db)
    result = tool.handler({
        "specialist_id": "does-not-exist",
        "message": "hello?",
    })
    assert result["error"] == "unknown_specialist"


def test_query_specialist_rejects_terminated_session(conv_db):
    """A session whose title was retitled to '[specialist-archived:...]'
    is no longer reachable via query_specialist."""
    _seed_session(
        conv_db, session_id="terminated-sess", agent="vett",
        title="[specialist-archived:done:node-1]",
    )
    tool = build_query_specialist_tool(conv_db_path=conv_db)
    result = tool.handler({
        "specialist_id": "terminated-sess",
        "message": "still there?",
    })
    assert result["error"] == "specialist_terminated"


def test_query_specialist_rejects_non_specialist_session(conv_db):
    """A regular chat session (not titled with the specialist prefix)
    can't be queried as a specialist."""
    _seed_session(
        conv_db, session_id="regular-sess", agent="vett",
        title="[direct:node-1]",
    )
    tool = build_query_specialist_tool(conv_db_path=conv_db)
    result = tool.handler({
        "specialist_id": "regular-sess",
        "message": "hi",
    })
    assert result["error"] == "specialist_terminated"


# ─── terminate_specialist ──────────────────────────────────────────────────


def test_terminate_specialist_archives_title_and_captures_ack(conv_db):
    _seed_session(
        conv_db, session_id="spec-end", agent="vett",
        title="[specialist:kernel_analyst:node-1]",
    )
    poster, calls = _ok_poster_factory(content="Acknowledged. Closing out.")
    tool = build_terminate_specialist_tool(
        conv_db_path=conv_db, http_poster=poster,
    )
    result = tool.handler({
        "specialist_id": "spec-end",
        "summary": "Found the 2x speedup in the attention reduction phase.",
    })
    assert result["specialist_id"] == "spec-end"
    assert result["archived_title"].startswith("[specialist-archived:")
    assert "kernel_analyst:node-1" in result["archived_title"]
    assert "Closing out" in result["final_ack"]
    # Title was rewritten in DB
    with sqlite3.connect(str(conv_db)) as con:
        new_title = con.execute(
            "SELECT title FROM conversation_meta WHERE session_id = ?",
            ("spec-end",),
        ).fetchone()[0]
    assert new_title.startswith("[specialist-archived:")
    # And it no longer counts against concurrency
    assert concurrency.count_active_specialists(conv_db) == 0


def test_terminate_specialist_idempotent_on_already_archived(conv_db):
    _seed_session(
        conv_db, session_id="done", agent="vett",
        title="[specialist-archived:done:node-1]",
    )
    tool = build_terminate_specialist_tool(conv_db_path=conv_db)
    result = tool.handler({
        "specialist_id": "done",
        "summary": "wrapping up",
    })
    assert result["error"] == "already_terminated"


def test_terminate_specialist_unknown_specialist(conv_db):
    tool = build_terminate_specialist_tool(conv_db_path=conv_db)
    result = tool.handler({
        "specialist_id": "unknown",
        "summary": "wrapping up",
    })
    assert result["error"] == "unknown_specialist"


def test_terminate_specialist_archives_even_if_ack_dispatch_fails(conv_db):
    """The terminate is authoritative — Aetheria's decision, not the
    specialist's cooperation. If the ack post fails, archive anyway."""
    _seed_session(
        conv_db, session_id="spec-fail", agent="vett",
        title="[specialist:flaky:node-1]",
    )
    def failing_poster(url, body, timeout):
        raise ConnectionError("simulated downstream failure")
    tool = build_terminate_specialist_tool(
        conv_db_path=conv_db, http_poster=failing_poster,
    )
    result = tool.handler({
        "specialist_id": "spec-fail",
        "summary": "done despite failure",
    })
    assert result["specialist_id"] == "spec-fail"
    assert result["archived_title"].startswith("[specialist-archived:")
    # Title is rewritten regardless of ack failure
    with sqlite3.connect(str(conv_db)) as con:
        new_title = con.execute(
            "SELECT title FROM conversation_meta WHERE session_id = ?",
            ("spec-fail",),
        ).fetchone()[0]
    assert new_title.startswith("[specialist-archived:")


# ─── concurrency helpers ────────────────────────────────────────────────────


def test_count_active_specialists_excludes_other_titles(conv_db):
    _seed_session(conv_db, session_id="s1", agent="vett",
                  title="[specialist:a:n1]")
    _seed_session(conv_db, session_id="s2", agent="vett",
                  title="[specialist:b:n2]")
    _seed_session(conv_db, session_id="s3", agent="vett",
                  title="[specialist-archived:c:n3]")
    _seed_session(conv_db, session_id="s4", agent="vett",
                  title="[direct:n4]")
    _seed_session(conv_db, session_id="s5", agent="vett",
                  title="some user-named session")
    assert concurrency.count_active_specialists(conv_db) == 2


def test_is_at_concurrency_cap(conv_db):
    assert not concurrency.is_at_concurrency_cap(conv_db)
    for i in range(3):
        _seed_session(conv_db, session_id=f"s{i}", agent="vett",
                      title=f"[specialist:n{i}:c{i}]")
    assert concurrency.is_at_concurrency_cap(conv_db)


# ─── full lifecycle integration ────────────────────────────────────────────


def test_full_lifecycle_spawn_query_terminate(conv_db):
    """Walk a specialist through spawn → query → terminate end-to-end."""
    # State accumulator: each call appends to this list
    posted = []

    def poster(url, body, timeout):
        posted.append({"url": url, "body": body})
        if url.endswith("/sessions"):
            sid = "lifecycle-sess"
            # Mirror the session into the conv_db like the real /sessions does
            _seed_session(
                conv_db, session_id=sid, agent=body["agent"],
                title=body["title"],
            )
            return {"session_id": sid, "agent": body["agent"]}
        # /chat — return distinct content per turn so we can track
        turn_count = sum(1 for p in posted if p["url"].endswith("/chat"))
        return {
            "content": f"turn-{turn_count}-response",
            "session_id": "lifecycle-sess",
            "finish_reason": "stop",
        }

    spawn = build_spawn_specialist_tool(conv_db_path=conv_db, http_poster=poster)
    query = build_query_specialist_tool(conv_db_path=conv_db, http_poster=poster)
    terminate = build_terminate_specialist_tool(
        conv_db_path=conv_db, http_poster=poster,
    )

    # Spawn
    spawn_result = spawn.handler(_spawn_args(name="lc_test"))
    assert spawn_result["specialist_id"] == "lifecycle-sess"
    assert concurrency.count_active_specialists(conv_db) == 1

    # Query
    query_result = query.handler({
        "specialist_id": "lifecycle-sess",
        "message": "What did you find?",
    })
    assert "turn-2" in query_result["response_content"]  # turn 1 was invocation

    # Terminate
    term_result = terminate.handler({
        "specialist_id": "lifecycle-sess",
        "summary": "Engagement complete; integrating findings.",
    })
    assert term_result["archived_title"].startswith("[specialist-archived:")
    assert concurrency.count_active_specialists(conv_db) == 0

    # Subsequent query should fail
    follow_up = query.handler({
        "specialist_id": "lifecycle-sess",
        "message": "one more thing",
    })
    assert follow_up["error"] == "specialist_terminated"
