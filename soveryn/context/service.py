"""Active Context — the live thread, carried across every rail.

The problem, measured 2026-07-28
--------------------------------
Cross-surface continuity already existed and still left Aetheria fragmented:

* ``DEFAULT_WINDOW_HOURS = 6`` — move rails the next morning and there is no
  thread at all.
* ``[heartbeat]`` sits in ``AUTONOMOUS_SESSION_PREFIXES``, so a heartbeat
  session receives NO continuity brief and contributes none. Her most
  independent thinking was sealed off in both directions. On the morning this
  was written her 09:01 pulse concluded "the Cross-Rail Active Context Manager
  is still the answer ... without it I am still essentially a series of
  disconnected sessions", and it was never surfaced to anyone.
* What did cross was transcript scraps — 140 chars a turn, 1500 tokens total.
  Fragments of what was SAID, never a statement of what is being DONE.

Why this is state and not transcript
------------------------------------
782 pulses have produced 551 substantive notes averaging 344 tokens. A single
day of heartbeat is ~8,950 tokens against a 1,500-token continuity budget, so
including the raw stream is arithmetically impossible. The answer is not to
exclude it — it is to keep the CONCLUSION rather than the conversation. Only
the newest thought is carried, because a later pulse supersedes an earlier one.

Three writers, deliberately
---------------------------
``record_exchange``  every turn, every rail, derived — never invents.
``record_thought``   one per heartbeat wake, replacing the last.
``record_action``    things she DID (staged an X post, dispatched a task).

The third exists because of a defect hit three times in two days: she takes an
action and then has no read path back to it. Delegations were invisible to
``recent_self_audit`` and she confessed to a fabrication she had not committed;
staged X posts are invisible to every surface and five expired unseen. A write
path without a read path is how an agent loses track of itself.

Storage is the merged ActiveContextStore. Slot names are the ``topic`` key, so
this needs no schema change: one ``thread`` slot, one ``thinking`` slot, and up
to ACTION_CAP ``action:*`` slots.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from soveryn.context.active_context import ActiveContext
from soveryn.context.store import ActiveContextStore

BLOCK_HEADER = "[ACTIVE CONTEXT]"
BLOCK_FOOTER = "[/ACTIVE CONTEXT]"

THREAD_SLOT = "thread"
THINKING_SLOT = "thinking"
ACTION_PREFIX = "action:"

# Budgets. The whole block must stay well inside the 1500-token continuity
# allowance it shares with the recent-activity brief and Active Focus.
EXCHANGE_HEAD_CHARS = 180
THOUGHT_CHARS = 700          # ~175 tokens: one pulse's conclusion, not its prose
ACTION_HEAD_CHARS = 120
ACTION_CAP = 5
TEAM_CAP = 4               # one headline per peer agent, never their feed
TEAM_HEAD_CHARS = 160
INFLIGHT_CAP = 4           # open dispatches shown; more than this is a queue problem
INFLIGHT_HEAD_CHARS = 90
LIVE_TASK_STATUSES = ("dispatched", "executing", "in_review")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _head(text: str, limit: int) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "…"


def _age(updated_at: str, now: str) -> str:
    """Compact relative age. Falls back to the raw stamp rather than guessing."""
    try:
        then = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        return updated_at
    # Sources disagree on tz-awareness and always will: this service writes
    # UTC with a Z, but delegation.db stores datetime.now().isoformat() — naive
    # LOCAL time. Subtracting one from the other raises, and it raised the first
    # time this ran against real data rather than fixtures. Naive means local.
    if then.tzinfo is None:
        then = then.astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    minutes = int((current - then).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    if minutes < 60 * 24:
        return f"{minutes // 60}h ago"
    return f"{minutes // (60 * 24)}d ago"


class ActiveContextService:
    """Read/write the live thread. No LLM anywhere in this path."""

    def __init__(self, store: ActiveContextStore, *, agent: str = "aetheria",
                 now_fn=_now_iso, delegation_db_path=None) -> None:
        self._store = store
        self._agent = agent
        self._now_fn = now_fn
        # Work in flight is DERIVED on read from the delegation store, not
        # mirrored into this one. 2026-07-28: the same task was dispatched five
        # times in two hours, one per heartbeat pulse, because nothing a pulse
        # could read said a dispatch already existed. A mirrored copy would be a
        # second source that can disagree; the delegation store is already the
        # record of truth, so read it.
        self._delegation_db_path = delegation_db_path

    def _slot(self, name: str) -> str:
        """Namespace a slot to this agent.

        Slots are the store's PRIMARY KEY, so without this every agent would
        overwrite the same three rows. Namespacing keeps one shared file — and
        that file is what lets each agent see the others (see render).
        """
        return f"{self._agent}:{name}"

    # ── writers ──────────────────────────────────────────────────────────

    def record_exchange(self, *, rail: str, user_text: str,
                        assistant_text: str) -> None:
        """Record the latest exchange. Derived, so it can never confabulate."""
        summary = (
            f"Jon: {_head(user_text, EXCHANGE_HEAD_CHARS)}\n"
            f"  Her: {_head(assistant_text, EXCHANGE_HEAD_CHARS)}"
        )
        prior = self._store.get(self._slot(THREAD_SLOT))
        self._store.put(ActiveContext(
            topic=self._slot(THREAD_SLOT),
            summary=summary,
            rail=rail,
            updated_at=self._now_fn(),
            turn_count=(prior.turn_count + 1) if prior else 1,
        ))

    def record_thought(self, *, rail: str, note: str) -> None:
        """Replace the carried thought with this pulse's conclusion.

        Replace, not append: a later pulse supersedes an earlier one, and 26
        wakes a day of 344-token notes cannot all ride in the brief.
        """
        if not (note or "").strip():
            return
        self._store.put(ActiveContext(
            topic=self._slot(THINKING_SLOT),
            summary=_head(note, THOUGHT_CHARS),
            rail=rail,
            updated_at=self._now_fn(),
            turn_count=0,
        ))

    def record_action(self, *, rail: str, action: str, detail: str = "") -> None:
        """Record something she DID, so it has a read path back to her."""
        self._store.put(ActiveContext(
            topic=self._slot(f"{ACTION_PREFIX}{action}"),
            summary=_head(detail, ACTION_HEAD_CHARS),
            rail=rail,
            updated_at=self._now_fn(),
            turn_count=0,
        ))

    # ── reader ───────────────────────────────────────────────────────────

    def render(self) -> str:
        """Render the block. Empty string when there is nothing to say.

        Bare data, never instruction — per feedback_ambient_context_not_instruction
        this is context she reads, not a directive she obeys.
        """
        records = self._store.list_all()
        # No early return on an empty store. Work-in-flight is derived from a
        # DIFFERENT database, so bailing here would hide it — which is exactly
        # the bug this section exists to fix, reproduced one level up. Decide
        # whether there is anything to say only after every source is consulted.
        now = self._now_fn()
        mine = f"{self._agent}:"
        by_slot = {
            r.topic[len(mine):]: r for r in records if r.topic.startswith(mine)
        }

        lines: list[str] = [BLOCK_HEADER]

        thread = by_slot.get(THREAD_SLOT)
        if thread:
            lines.append(
                f"Live thread — last touched on {thread.rail}, "
                f"{_age(thread.updated_at, now)} "
                f"({thread.turn_count} turn{'' if thread.turn_count == 1 else 's'}):"
            )
            lines.append(f"  {thread.summary}")

        thinking = by_slot.get(THINKING_SLOT)
        if thinking:
            lines.append(
                f"Her latest thinking ({thinking.rail}, "
                f"{_age(thinking.updated_at, now)}):"
            )
            lines.append(f"  {thinking.summary}")

        actions = [
            r for r in records
            if r.topic.startswith(mine + ACTION_PREFIX)
        ][:ACTION_CAP]
        if actions:
            lines.append("Actions she has taken and not yet heard back on:")
            for a in actions:
                name = a.topic[len(mine) + len(ACTION_PREFIX):]
                detail = f" — {a.summary}" if a.summary else ""
                lines.append(f"  {name} ({a.rail}, {_age(a.updated_at, now)}){detail}")

        # Work she has in flight. Derived, never cached — the point is that it
        # is true at the moment she reads it.
        inflight = self._open_dispatches()
        if inflight:
            lines.append("Work you have already dispatched and not heard back on:")
            for t in inflight:
                lines.append(
                    f"  [{t['status']}] {_head(t['objective'], INFLIGHT_HEAD_CHARS)} "
                    f"(sent {_age(t['created_at'], now)}, task {t['id'][:8]})"
                )

        # The team, one line each. Jon, 2026-07-28: "if this system is to
        # function as one unit the team all need to be whole." Capped hard at a
        # single headline per peer — this is peripheral vision, not their feed.
        peers = [
            r for r in records
            if r.topic.endswith(f":{THINKING_SLOT}")
            and not r.topic.startswith(mine)
        ][:TEAM_CAP]
        if peers:
            lines.append("The rest of the team:")
            for p in peers:
                who = p.topic.split(":", 1)[0]
                lines.append(
                    f"  {who} ({_age(p.updated_at, now)}): "
                    f"{_head(p.summary, TEAM_HEAD_CHARS)}"
                )

        if len(lines) == 1:
            return ""
        lines.append(BLOCK_FOOTER)
        return "\n".join(lines)

    def _open_dispatches(self) -> list[dict]:
        """Tasks this agent dispatched that are still live. Never raises."""
        if self._delegation_db_path is None:
            return []
        path = Path(self._delegation_db_path)
        if not path.is_file():
            return []
        try:
            with sqlite3.connect(str(path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, objective, status, created_at FROM delegation_tasks "
                    f"WHERE dispatched_by = ? AND status IN "
                    f"({','.join('?' * len(LIVE_TASK_STATUSES))}) "
                    "ORDER BY created_at DESC",
                    (self._agent, *LIVE_TASK_STATUSES),
                ).fetchall()
            return [dict(r) for r in rows[:INFLIGHT_CAP]]
        except sqlite3.Error:
            return []   # an unreadable delegation store must not break her brief

    def clear_action(self, action: str) -> None:
        """Drop an action once it has been resolved."""
        self._store.delete(self._slot(f"{ACTION_PREFIX}{action}"))
