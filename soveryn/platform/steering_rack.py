"""Steering Rack — circuit breaker for repeated near-identical empty searches.

Named per Aetheria's 2026-06-13 Harness-1 verdict: "a high-performance
engine with a broken steering rack — she can go fast, but she can't stop
when she hits a wall." Harness-1 issued 17 nearly-identical reformulations
of the same subclaim, all returning empty, before the trajectory cap fired.
This module is the cheapest peer-mechanical correction:

  count empties + measure paraphrase similarity + return a "you're in a
  loop" result.

Design:
 - Per-session per-tool sliding window of recent (args, was_empty) entries.
 - Trip rule: last N (default 3) calls to the same tool were all empty AND
   all pairs had token-set Jaccard >= threshold (default 0.7).
 - Empty detection: JSON-decoded result has zero items in any primary
   collection field (results / nodes / matches / items / hits). Falls open
   on parse failure or unknown shape — opaque tools can't false-trip.
 - Trip is sticky per (session, tool): once tripped, every subsequent call
   short-circuits with the same synthetic error. No automatic reset. The
   model has been told "you're in a loop, stop" — trying again next turn
   is not useful.
 - State is in-memory only; no disk persistence. Process restart resets.

The trip outcome is a tool RESULT (not an exception): a dict with `error:
"steering_rack_open"` and a steering hint. AgentLoop wraps it the same way
as a real tool result, so it surfaces to the model as observable feedback
AND lands in the Black Box trajectory for post-hoc audit.
"""
from __future__ import annotations

import json
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any


# Tools that ARE retrieval and SHOULD be watched. Anything not on this list
# is invisible to the steering rack — that way a write-tool like attic_write
# never trips no matter how many times it's invoked.
_DEFAULT_WATCHED_TOOLS: frozenset[str] = frozenset({
    "web_search",
    "fan_out_search",
    "search_corpus",
    "search_lattice",
    "attic_lookup",
    "read_document",
    "browser_fetch",
})


# Primary collection fields scanned to detect "empty result". When the
# JSON-decoded result has one of these as a key and its value is a list
# of length 0, the call counts as empty. If none of these keys appear, we
# treat the call as NOT empty (fall open) — better to let a death loop run
# than to false-trip on an opaque tool.
_COLLECTION_FIELDS: tuple[str, ...] = (
    "results", "nodes", "matches", "items", "hits", "documents",
)


_TOKEN_RE = re.compile(r"\w+")


def _tokenize(text: str) -> frozenset[str]:
    """Tokenize for Jaccard. Lower-cased, alpha-numeric runs only."""
    return frozenset(t.lower() for t in _TOKEN_RE.findall(text or ""))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def is_empty_result(result_content: str) -> bool:
    """Inspect a tool's JSON-serialised result content and return True if
    the result is a "no items found" response.

    Falls open: any parse failure or unrecognised shape returns False so
    the breaker does NOT trip on opaque tools.
    """
    if not result_content:
        return False
    try:
        decoded = json.loads(result_content)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(decoded, dict):
        return False
    # Tool returned an error → not an "empty search" per se. Don't count.
    if decoded.get("error"):
        return False
    for field in _COLLECTION_FIELDS:
        value = decoded.get(field)
        if isinstance(value, list):
            if len(value) == 0:
                return True
            return False  # found a non-empty collection → real hit
    # No known collection field → fall open.
    return False


@dataclass
class _Entry:
    args_text: str
    args_tokens: frozenset[str]
    was_empty: bool


@dataclass
class SteeringRack:
    """Per-session per-tool circuit breaker.

    Thread-safe: each observe / should_short_circuit / synthetic_error op
    is guarded by a single instance-level lock. Contention is low (one op
    per tool dispatch); a lock is simpler than per-key locks.
    """

    watched_tools: frozenset[str] = field(default_factory=lambda: _DEFAULT_WATCHED_TOOLS)
    sim_threshold: float = 0.7
    consecutive_empties_threshold: int = 3
    _windows: dict[tuple[str, str], deque[_Entry]] = field(default_factory=dict)
    _tripped: set[tuple[str, str]] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def is_watched(self, tool_name: str) -> bool:
        return tool_name in self.watched_tools

    def should_short_circuit(self, *, session_id: str, tool_name: str) -> bool:
        """Pre-dispatch check. Returns True if the (session, tool) pair is
        already tripped (stays tripped for the rest of the process lifetime).
        """
        if not self.is_watched(tool_name):
            return False
        with self._lock:
            return (session_id, tool_name) in self._tripped

    def observe(
        self,
        *,
        session_id: str,
        tool_name: str,
        args_text: str,
        result_content: str,
    ) -> bool:
        """Record one tool dispatch. Returns True if this observation
        crossed the trip threshold and the breaker is now open."""
        if not self.is_watched(tool_name):
            return False
        was_empty = is_empty_result(result_content)
        with self._lock:
            key = (session_id, tool_name)
            window = self._windows.setdefault(
                key, deque(maxlen=self.consecutive_empties_threshold)
            )
            window.append(_Entry(
                args_text=args_text,
                args_tokens=_tokenize(args_text),
                was_empty=was_empty,
            ))
            if key in self._tripped:
                return True
            if len(window) < self.consecutive_empties_threshold:
                return False
            # All must be empty
            if not all(e.was_empty for e in window):
                return False
            # All pairs must be near-identical (Jaccard >= threshold)
            entries = list(window)
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    if _jaccard(entries[i].args_tokens, entries[j].args_tokens) < self.sim_threshold:
                        return False
            self._tripped.add(key)
            return True

    def synthetic_error(self, *, tool_name: str) -> dict[str, Any]:
        """Build the synthetic error payload returned when the circuit is
        open. AgentLoop serialises this as the tool result content."""
        return {
            "error": "steering_rack_open",
            "message": (
                f"You've made {self.consecutive_empties_threshold} near-identical empty calls "
                f"to {tool_name}. The query is stuck in a loop. Try a different angle, a "
                f"different tool, or stop searching and answer with what you have."
            ),
            "consecutive_empty_threshold": self.consecutive_empties_threshold,
        }
