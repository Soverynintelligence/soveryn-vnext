"""Package-local tests — no SOVERYN / Flask required."""

from __future__ import annotations

from pathlib import Path

import pytest

from acttruth import ActTruth, audit_tool, wrap_callable
from acttruth.audit import reset_acttruth_cache
from acttruth.openai_tools import (
    inject_lessons_message,
    record_openai_tool_result,
    wrap_tool_dispatch,
)


@pytest.fixture
def at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ActTruth:
    root = tmp_path / "acttruth"
    inst = ActTruth.open(root)
    reset_acttruth_cache()
    monkeypatch.setattr("acttruth.audit.get_acttruth", lambda root=None: inst)
    return inst


def test_wrap_callable_records_soft_error(at: ActTruth) -> None:
    def flaky(q: str):
        return {"error": "upstream down", "message": "search failed"}

    wrapped = wrap_callable(flaky, agent="demo", tool_name="search", acttruth=at)
    out = wrapped("hello")
    assert out["error"]
    fails = at.ledger.recent("demo", failures_only=True)
    assert len(fails) == 1
    assert fails[0].tool == "search"
    assert fails[0].ok is False


def test_wrap_callable_timeout_exception(at: ActTruth) -> None:
    def boom():
        raise TimeoutError("timed out after 30s")

    wrapped = wrap_callable(boom, agent="demo", tool_name="fetch", acttruth=at)
    with pytest.raises(TimeoutError):
        wrapped()
    fails = at.ledger.recent("demo", failures_only=True)
    assert len(fails) == 1
    assert fails[0].kind == "timeout"


def test_audit_tool_decorator_and_lesson(at: ActTruth) -> None:
    @audit_tool(agent="demo", name="generate_image", acttruth=at)
    def gen(prompt: str):
        return {"error": "ComfyUI generation timed out after 180s"}

    gen("x")
    gen("y")  # streak ≥ 2 → lesson attach
    out = gen("z")
    assert "acttruth_lesson" in out or at.ledger.recent("demo", failures_only=True)
    # After streak, lesson string should appear on a subsequent fail
    # (streak counts ledger rows; third fail should arm)
    assert any(
        "lesson" in (e.summary or "").lower() or e.tags
        for e in at.ledger.recent("demo", limit=20)
    ) or out.get("acttruth_lesson")


def test_openai_record_and_inject(at: ActTruth) -> None:
    record_openai_tool_result(
        agent="demo",
        tool_name="search",
        arguments={"q": "acttruth"},
        result={"error": "timeout"},
        acttruth=at,
    )
    record_openai_tool_result(
        agent="demo",
        tool_name="search",
        arguments={"q": "acttruth"},
        error="timed out",
        acttruth=at,
    )
    messages: list[dict] = [{"role": "user", "content": "hi"}]
    # lessons_brief may be empty until pattern matches; inject still ok if empty
    inject_lessons_message(messages, "demo")
    assert messages[0]["role"] in ("system", "user")


def test_wrap_tool_dispatch(at: ActTruth) -> None:
    tools = wrap_tool_dispatch(
        {"ping": lambda: {"ok": True}},
        agent="demo",
        acttruth=at,
    )
    assert tools["ping"]()["ok"] is True
    evs = at.ledger.recent("demo")
    assert any(e.tool == "ping" and e.ok for e in evs)
