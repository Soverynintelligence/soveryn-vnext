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
