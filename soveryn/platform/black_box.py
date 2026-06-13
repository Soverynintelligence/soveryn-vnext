"""Black Box — per-turn trajectory + failure-mode telemetry for AgentLoop.

The live chat path (sync + streaming) historically had no audit trail for
tool activity. When a turn went sideways (Vett locked in a search loop,
Aetheria hit tool_round_limit, a tool errored silently), there was nothing
to grep later. The 2026-06-13 Harness-1 eval made the gap concrete: the
harness eval runner records full Trajectory JSON, the live chat path
records only the final assistant text.

This module mirrors the harness Trajectory shape (subset — see
soveryn/agents/vett/harness/vendor/trajectory.py) so post-hoc comparisons
between Harness-1-style evals and live chat turns are apples-to-apples.

Output: JSONL, one line per turn that had >= 1 tool call, at
data/black_box/<agent>/<session_id>.jsonl. Greppable with jq, zero DB
schema migration, append-only.

Telemetry block carries the failure-mode flags Aetheria's verdict called
out: explicit finish_reason ("stop" / "tool_round_limit" / "empty_generation"
/ etc.), num_rounds, per-tool call counts, error count, wall time.
"""
from __future__ import annotations

import json
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any


def _safe_filename(value: str) -> str:
    """Strip path separators so a session_id can't escape the per-agent dir."""
    return value.replace("/", "_").replace("\\", "_").replace("\x00", "_")


class BlackBox:
    """Writer for per-agent trajectory JSONL files.

    Thread-safe: file appends are serialised behind a per-instance lock so
    concurrent AgentLoop turns (different sessions, same agent) can't
    interleave bytes mid-line.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def begin_turn(
        self,
        *,
        session_id: str,
        agent: str,
        user_message: str,
    ) -> "TurnRecorder":
        """Open a recorder for a single turn. Returns a fresh TurnRecorder.

        The recorder is a no-op until at least one action is recorded, so
        callers can blindly begin_turn() at the top of every turn — turns
        that never call tools produce zero disk writes.
        """
        return TurnRecorder(
            black_box=self,
            session_id=session_id,
            agent=agent,
            user_message=user_message,
        )

    def _write_line(self, agent: str, session_id: str, line: dict[str, Any]) -> Path:
        """Append one JSON line. Returns the path written for testability."""
        agent_dir = self.root / _safe_filename(agent)
        agent_dir.mkdir(parents=True, exist_ok=True)
        path = agent_dir / f"{_safe_filename(session_id)}.jsonl"
        encoded = json.dumps(line, ensure_ascii=False, default=str)
        with self._lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(encoded + "\n")
        return path


@dataclass
class TurnRecorder:
    """One turn's trajectory accumulator. Mutated through record_* methods.

    finalize() writes a JSONL line ONLY if at least one action was recorded.
    No-op for turns that produced a final answer in one shot — by design,
    so we don't drown the audit log in trivial chat exchanges.
    """

    black_box: BlackBox
    session_id: str
    agent: str
    user_message: str
    _started_monotonic: float = field(default_factory=monotonic)
    _started_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))
    _events: list[dict[str, Any]] = field(default_factory=list)
    _tool_call_counts: Counter = field(default_factory=Counter)
    _tool_error_count: int = 0
    _num_rounds: int = 0
    _finalized: bool = False

    def record_action(
        self,
        *,
        round_index: int,
        tool_calls: list[dict[str, Any]],
        content: str | None,
    ) -> None:
        """Capture the model's action for one round of the tool loop.

        `tool_calls` is the OpenAI-shape list off ChatResponse.tool_calls.
        `content` is whatever the model emitted alongside the call request
        (often empty when it's just routing through tools).
        """
        normalised: list[dict[str, Any]] = []
        for tc in tool_calls:
            function = tc.get("function") or {}
            name = str(function.get("name") or "")
            normalised.append({
                "id": str(tc.get("id") or ""),
                "name": name,
                "arguments": str(function.get("arguments") or ""),
            })
            if name:
                self._tool_call_counts[name] += 1
        self._events.append({
            "type": "action",
            "round": round_index,
            "content": content or "",
            "tool_calls": normalised,
        })
        self._num_rounds += 1

    def record_observation(
        self,
        *,
        round_index: int,
        results: list[dict[str, Any]],
    ) -> None:
        """Capture tool results for the round just dispatched.

        `results` is a list of {call_id, name, content, error} dicts. `error`
        is a string when the tool raised, None on success.
        """
        for r in results:
            if r.get("error"):
                self._tool_error_count += 1
        self._events.append({
            "type": "observation",
            "round": round_index,
            "results": results,
        })

    def finalize(
        self,
        *,
        final_content: str,
        finish_reason: str,
        usage: dict[str, Any] | None = None,
    ) -> Path | None:
        """Flush JSONL line and return the path written, OR None if no tool
        activity was recorded (one-shot turn — nothing to audit).

        Idempotent: calling twice is a no-op. The exception-path callers
        (AgentLoopError branches in loop.py) finalize with the failure mode
        as finish_reason so failures are part of the audit trail too.
        """
        if self._finalized:
            return None
        self._finalized = True
        if self._num_rounds == 0:
            return None
        wall_time_ms = int((monotonic() - self._started_monotonic) * 1000)
        line = {
            "session_id": self.session_id,
            "agent": self.agent,
            "started_at": self._started_at,
            "user_message": self.user_message,
            "actions_and_observations": self._events,
            "final_content": final_content,
            "finish_reason": finish_reason,
            "telemetry": {
                "num_rounds": self._num_rounds,
                "tool_calls": dict(self._tool_call_counts),
                "tool_error_count": self._tool_error_count,
                "tool_round_limit_hit": finish_reason == "tool_round_limit",
                "wall_time_ms": wall_time_ms,
                "finish_reason": finish_reason,
                "usage": usage or {},
            },
        }
        return self.black_box._write_line(self.agent, self.session_id, line)
