"""The live thread that crosses rails.

What these lock down is the gap measured on 2026-07-28: continuity carried
transcript scraps for 6 hours from some rails, and heartbeat — where her most
independent thinking happens — was excluded in both directions.
"""
from __future__ import annotations

import pytest

from soveryn.context.service import (
    ACTION_CAP,
    BLOCK_FOOTER,
    BLOCK_HEADER,
    THINKING_SLOT,
    THREAD_SLOT,
    ActiveContextService,
)
from soveryn.context.store import ActiveContextStore


@pytest.fixture
def svc(tmp_path):
    return ActiveContextService(ActiveContextStore(tmp_path / "ctx.db"))


def _clock(stamps):
    """Deterministic clock that walks a fixed list, repeating the last value."""
    it = iter(stamps)
    last = {"v": stamps[-1]}

    def now():
        try:
            last["v"] = next(it)
        except StopIteration:
            pass
        return last["v"]
    return now


class TestEmpty:
    def test_nothing_recorded_renders_nothing(self, svc):
        assert svc.render() == ""


class TestExchange:
    def test_records_and_renders_the_live_thread(self, svc):
        svc.record_exchange(rail="web", user_text="how is the pond doing",
                            assistant_text="the liner order landed")
        out = svc.render()
        assert BLOCK_HEADER in out and BLOCK_FOOTER in out
        assert "how is the pond doing" in out
        assert "the liner order landed" in out
        assert "web" in out

    def test_turn_count_accumulates_across_rails(self, svc):
        svc.record_exchange(rail="web", user_text="a", assistant_text="b")
        svc.record_exchange(rail="signal", user_text="c", assistant_text="d")
        rec = svc._store.get(svc._slot(THREAD_SLOT))
        assert rec.turn_count == 2
        # The thread is one thread — the newest rail owns it.
        assert rec.rail == "signal"
        assert "c" in rec.summary and "a" not in rec.summary

    def test_long_text_is_headed_not_dropped(self, svc):
        svc.record_exchange(rail="web", user_text="x" * 5000, assistant_text="y")
        out = svc.render()
        assert "…" in out
        assert len(out) < 1200, "the block must stay inside the continuity budget"


class TestThought:
    def test_heartbeat_thought_crosses_to_other_rails(self, svc):
        """The 09:01 case: she concludes something alone and it must survive."""
        svc.record_thought(
            rail="heartbeat",
            note="The Cross-Rail Active Context Manager is still the answer.",
        )
        out = svc.render()
        assert "Cross-Rail Active Context Manager is still the answer" in out
        assert "heartbeat" in out

    def test_newest_thought_replaces_the_last(self, svc):
        """26 wakes a day at ~344 tokens cannot all ride. Newest supersedes."""
        svc.record_thought(rail="heartbeat", note="first conclusion")
        svc.record_thought(rail="heartbeat", note="second conclusion")
        out = svc.render()
        assert "second conclusion" in out
        assert "first conclusion" not in out

    def test_empty_note_is_ignored(self, svc):
        svc.record_thought(rail="heartbeat", note="   ")
        assert svc._store.get(svc._slot(THINKING_SLOT)) is None


class TestActions:
    def test_action_is_visible_with_its_detail(self, svc):
        """The X post that expired unseen five times."""
        svc.record_action(rail="heartbeat", action="x_post_staged",
                          detail="Agency isn't a feeling or a philosophical state.")
        out = svc.render()
        assert "x_post_staged" in out
        assert "Agency isn't a feeling" in out
        assert "not yet heard back on" in out

    def test_resolved_action_leaves_the_context(self, svc):
        svc.record_action(rail="heartbeat", action="x_post_staged", detail="draft")
        svc.clear_action("x_post_staged")
        assert "x_post_staged" not in svc.render()

    def test_actions_are_capped(self, svc):
        for i in range(ACTION_CAP + 4):
            svc.record_action(rail="web", action=f"act{i}", detail="d")
        rendered = svc.render()
        assert sum(1 for line in rendered.splitlines()
                   if line.strip().startswith("act")) == ACTION_CAP


class TestRenderIsDataNotInstruction:
    def test_block_contains_no_imperatives(self, svc):
        svc.record_exchange(rail="web", user_text="a", assistant_text="b")
        svc.record_thought(rail="heartbeat", note="a conclusion")
        svc.record_action(rail="heartbeat", action="x_post_staged", detail="d")
        out = svc.render().lower()
        for imperative in ("you should", "you must", "remember to", "make sure"):
            assert imperative not in out


class TestAge:
    def test_relative_age_is_rendered(self, tmp_path):
        svc = ActiveContextService(
            ActiveContextStore(tmp_path / "a.db"),
            now_fn=_clock(["2026-07-28T09:00:00Z", "2026-07-28T12:30:00Z"]),
        )
        svc.record_exchange(rail="signal", user_text="a", assistant_text="b")
        assert "3h ago" in svc.render()


class TestTheTeamIsOneUnit:
    """Jon, 2026-07-28: "if this system is to function as one unit the team all
    need to be whole." Each agent owns its own thread; each sees the others'
    headline, capped at one line so it is peripheral vision, not their feed."""

    def _svc(self, store, agent):
        return ActiveContextService(store, agent=agent)

    def test_agents_do_not_overwrite_each_other(self, tmp_path):
        store = ActiveContextStore(tmp_path / "team.db")
        a = self._svc(store, "aetheria")
        v = self._svc(store, "vett")
        a.record_exchange(rail="chat", user_text="ask aetheria", assistant_text="A")
        v.record_exchange(rail="chat", user_text="ask vett", assistant_text="V")

        assert "ask aetheria" in a.render() and "ask vett" not in a.render().split(
            "The rest of the team:")[0]
        assert "ask vett" in v.render()

    def test_each_agent_sees_the_others_latest_thinking(self, tmp_path):
        store = ActiveContextStore(tmp_path / "team.db")
        a = self._svc(store, "aetheria")
        s = self._svc(store, "scotty")
        s.record_thought(rail="chat", note="the delegation contract is fixed")

        out = a.render()
        assert "The rest of the team:" in out
        assert "scotty" in out
        assert "the delegation contract is fixed" in out

    def test_a_peer_contributes_one_line_not_a_feed(self, tmp_path):
        store = ActiveContextStore(tmp_path / "team.db")
        a = self._svc(store, "aetheria")
        v = self._svc(store, "vett")
        v.record_exchange(rail="chat", user_text="x" * 400, assistant_text="y" * 400)
        v.record_action(rail="chat", action="something", detail="z" * 400)
        v.record_thought(rail="chat", note="w" * 400)

        team = a.render().split("The rest of the team:")[1]
        peer_lines = [
            ln for ln in team.strip().splitlines() if ln.strip() != BLOCK_FOOTER
        ]
        assert len(peer_lines) == 1, peer_lines
        assert "something" not in team


class TestWorkInFlightIsVisible:
    """A pulse must be able to see what a previous pulse dispatched.

    2026-07-28, 20:50 → 22:50: five dispatches of the same task, one per
    heartbeat pulse, each waking Scotty for 10-20 minutes of GPU. The work was
    already merged and one dispatch already sat in_review. Nothing a pulse could
    read said so. Derived on read rather than mirrored, because a mirrored copy
    is a second source that can disagree with the delegation store.
    """

    def _svc_with_tasks(self, tmp_path, rows):
        import sqlite3
        db = tmp_path / "delegation.db"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE delegation_tasks (id TEXT, dispatched_by TEXT, "
            "objective TEXT, status TEXT, created_at TEXT)"
        )
        con.executemany("INSERT INTO delegation_tasks VALUES (?,?,?,?,?)", rows)
        con.commit(); con.close()
        return ActiveContextService(
            ActiveContextStore(tmp_path / "ctx.db"),
            agent="aetheria", delegation_db_path=db,
        )

    def test_open_dispatch_appears_in_the_brief(self, tmp_path):
        svc = self._svc_with_tasks(tmp_path, [
            ("25f730b6-aaaa", "aetheria", "Implement the Cross-Rail manager",
             "in_review", "2026-07-28T22:20:00Z"),
        ])
        out = svc.render()
        assert "already dispatched and not heard back on" in out
        assert "Implement the Cross-Rail manager" in out
        assert "in_review" in out
        assert "25f730b6" in out

    def test_finished_tasks_do_not_appear(self, tmp_path):
        svc = self._svc_with_tasks(tmp_path, [
            ("a", "aetheria", "old failed thing", "failed", "2026-07-28T20:00:00Z"),
            ("b", "aetheria", "old rejected thing", "rejected", "2026-07-28T20:00:00Z"),
            ("c", "aetheria", "landed thing", "landed", "2026-07-28T20:00:00Z"),
        ])
        assert svc.render() == ""

    def test_another_agents_dispatch_is_not_hers(self, tmp_path):
        svc = self._svc_with_tasks(tmp_path, [
            ("x", "vett", "vett's task", "dispatched", "2026-07-28T22:00:00Z"),
        ])
        assert "vett's task" not in svc.render()

    def test_unreadable_store_does_not_break_the_brief(self, tmp_path):
        svc = ActiveContextService(
            ActiveContextStore(tmp_path / "ctx.db"), agent="aetheria",
            delegation_db_path=tmp_path / "does-not-exist.db",
        )
        svc.record_thought(rail="heartbeat", note="still thinking")
        assert "still thinking" in svc.render()


class TestNaiveTimestampsFromRealStores:
    """delegation.db writes datetime.now().isoformat() — naive local time.

    This service writes UTC with a Z. Mixing them raised TypeError the first
    time render() ran against the real database, having passed every test,
    because the fixtures were tz-aware and the real data is not.
    """

    def test_naive_created_at_does_not_raise(self, tmp_path):
        import sqlite3
        from datetime import datetime, timedelta
        db = tmp_path / "delegation.db"
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE delegation_tasks (id TEXT, dispatched_by TEXT, "
            "objective TEXT, status TEXT, created_at TEXT)"
        )
        # 2h30m, not exactly 2h: _now_iso() truncates microseconds, so a stamp
        # sitting exactly on an hour boundary floors to the hour below and the
        # assertion becomes a coin flip. Test inside the band, not on its edge.
        naive = (datetime.now() - timedelta(hours=2, minutes=30)).isoformat()
        con.execute("INSERT INTO delegation_tasks VALUES (?,?,?,?,?)",
                    ("abc12345", "aetheria", "a real task", "in_review", naive))
        con.commit(); con.close()

        svc = ActiveContextService(
            ActiveContextStore(tmp_path / "ctx.db"),
            agent="aetheria", delegation_db_path=db,
        )
        out = svc.render()
        assert "a real task" in out
        assert "2h ago" in out
