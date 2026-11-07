"""Tests for the distill memory cap (regression 2026-11-07).

Uncapped, 400+ accumulated reflections produced an ~82k-char prompt that
exceeded the cognition model's 16k ctx — HTTP 400 on every deep cycle since
Oct 20, so the sense-of-us note never updated.
"""

from __future__ import annotations

from soveryn.agents.cognition import distill as distill_mod
from soveryn.agents.cognition.distill import DEFAULT_MAX_MEMORIES, _max_memories
from soveryn.agents.cognition.types import ReflectionMemory


def _mem(i: int) -> ReflectionMemory:
    return ReflectionMemory(
        id=f"m{i}",
        text=f"observation {i}",
        scope="manner",
        citations=(f"turn:s:{i}",),
        jon_originated=False,
        created_at=f"2026-11-0{(i % 7) + 1}T00:00:00",
    )


class TestMaxMemories:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("SOVERYN_COGNITION_DISTILL_MAX_MEMORIES", raising=False)
        assert _max_memories() == DEFAULT_MAX_MEMORIES

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SOVERYN_COGNITION_DISTILL_MAX_MEMORIES", "10")
        assert _max_memories() == 10

    def test_bad_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("SOVERYN_COGNITION_DISTILL_MAX_MEMORIES", "banana")
        assert _max_memories() == DEFAULT_MAX_MEMORIES


class TestDistillCap:
    def _run(self, memories, monkeypatch, limit=None):
        """Drive distill() with a fake store/chat_fn; return the prompt text."""
        captured = {}

        def chat_fn(system, user):
            captured["system"] = system
            captured["user"] = user
            return "note line"

        class FakeStore:
            def current_note_id(self):
                return None

            def write_note_version(self, content, supersedes=None):
                captured["written"] = content
                return content

        if limit is not None:
            monkeypatch.setenv("SOVERYN_COGNITION_DISTILL_MAX_MEMORIES", str(limit))
        distill_mod.distill("aetheria", memories, FakeStore(), chat_fn)
        return captured

    def test_cap_keeps_most_recent(self, monkeypatch):
        memories = [_mem(i) for i in range(100)]
        captured = self._run(memories, monkeypatch, limit=40)
        assert "observation 59" not in captured["user"]
        assert "observation 99" in captured["user"]

    def test_under_cap_sends_all(self, monkeypatch):
        memories = [_mem(i) for i in range(10)]
        captured = self._run(memories, monkeypatch, limit=40)
        assert "observation 0" in captured["user"]
        assert "observation 9" in captured["user"]

    def test_zero_disables_cap(self, monkeypatch):
        memories = [_mem(i) for i in range(100)]
        captured = self._run(memories, monkeypatch, limit=0)
        assert "observation 0" in captured["user"]

    def test_order_preserved_oldest_first(self, monkeypatch):
        memories = [_mem(i) for i in range(50)]
        captured = self._run(memories, monkeypatch, limit=10)
        u = captured["user"]
        assert u.index("observation 40") < u.index("observation 49")
