"""ActTruth proof suite.

Proves the product claims:
  1) Quiet failures become visible truth (not silence).
  2) Soft error dicts count as failures.
  3) Unprompted spend can be exhausted (stand-down).
  4) Repeat same-tool FAILs arm a LESSON (anti-loop).
  5) Lessons reach the agent (prelude brief + in-band tool result).
  6) Crew includes Kernel as a ledgered agent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from soveryn.platform.acttruth.budget import BudgetPolicy, BudgetStore
from soveryn.platform.acttruth.hooks import (
    get_acttruth,
    record_tool_audit,
    reset_acttruth_cache,
)
from soveryn.platform.acttruth.ledger import ActTruth, LedgerStore
from soveryn.platform.acttruth.lessons import (
    classify_error,
    lessons_brief,
    lessons_from_events,
    maybe_lesson_for_tool_result,
)
from soveryn.platform.acttruth.unprompted import CREW_AGENTS, crew_status


def test_acttruth_dir_env_isolates_from_house_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AgentLoop tests must not read the live house ledger."""
    iso = tmp_path / "iso-acttruth"
    monkeypatch.setenv("ACTTRUTH_DIR", str(iso))
    from soveryn.platform.acttruth.hooks import reset_acttruth_cache
    from soveryn.platform.acttruth.paths import default_acttruth_dir

    reset_acttruth_cache()
    assert default_acttruth_dir() == iso


@pytest.fixture
def at(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ActTruth:
    """Isolated ActTruth root — no pollution of house data/."""
    root = tmp_path / "acttruth"
    inst = ActTruth.open(root)
    reset_acttruth_cache()

    def _get(root=None):
        return inst

    # Portable package is source of truth; patch its getter (late-imported via _at()).
    monkeypatch.setattr("acttruth.audit.get_acttruth", _get)
    monkeypatch.setattr("soveryn.platform.acttruth.hooks.get_acttruth", _get)
    monkeypatch.setattr("soveryn.platform.acttruth.lessons.get_acttruth", _get)
    monkeypatch.setattr("soveryn.platform.acttruth.unprompted.get_acttruth", _get)
    return inst


# ─── Claim 1: quiet failures become visible ──────────────────────────────────


def test_proof_quiet_timeout_is_visible_fail(at: ActTruth) -> None:
    record_tool_audit(
        agent="aetheria",
        tool_name="generate_image",
        args={"prompt": "cosmic brain"},
        ok=False,
        error="ComfyUI generation timed out after 180s",
        acttruth=at,
    )
    fails = at.ledger.recent("aetheria", failures_only=True)
    assert len(fails) == 1
    assert fails[0].kind == "timeout"
    assert fails[0].ok is False
    brief = at.ledger.recall_brief("aetheria")
    assert "ACTTRUTH" in brief
    assert "FAIL" in brief
    assert "generate_image" in brief


def test_proof_soft_error_dict_counts_as_failure(at: ActTruth) -> None:
    """Handlers that return {error:...} without raising must still ledger FAIL."""
    record_tool_audit(
        agent="aetheria",
        tool_name="generate_image",
        args={"prompt": "x"},
        ok=True,  # registry thinks ok — payload lies
        result={"error": "comfyui_unreachable", "message": "could not reach"},
        acttruth=at,
    )
    events = at.ledger.recent("aetheria", limit=5)
    assert events
    assert events[0].ok is False


# ─── Claim 2: unprompted budget stand-down ───────────────────────────────────


def test_proof_budget_exhaustion_stand_down(tmp_path: Path) -> None:
    store = BudgetStore(
        tmp_path / "budget.db",
        policy=BudgetPolicy(window_seconds=3600, max_unprompted_actions=2),
    )
    assert store.check("aetheria").allowed
    store.spend("aetheria", kind="heartbeat_action", summary="one")
    store.spend("aetheria", kind="heartbeat_action", summary="two")
    d = store.check("aetheria")
    assert d.allowed is False
    assert d.remaining == 0
    note = d.stand_down_note.lower()
    assert "exhausted" in note or "budget" in note
    assert "do not call tools" in note or "quiet" in note


# ─── Claim 3: repeat failures → lesson (anti-loop) ───────────────────────────


def test_proof_repeat_timeout_arms_lesson(at: ActTruth) -> None:
    for i in range(2):
        at.ledger.record(
            agent_id="aetheria",
            kind="timeout",
            summary=f"generate_image FAILED — timed out after {180 + i}s",
            ok=False,
            tool="generate_image",
            tags=("quiet_failure",),
        )
    lessons = lessons_from_events(
        at.ledger.recent("aetheria", limit=20, failures_only=True)
    )
    assert lessons, "two generate_image timeouts must arm a lesson"
    assert lessons[0].tool == "generate_image"
    assert lessons[0].error_class == "timeout"
    assert lessons[0].streak >= 2

    brief = lessons_brief("aetheria")
    assert "ACTTRUTH LESSONS" in brief
    assert "generate_image" in brief
    assert "Do NOT repeat" in brief


def test_proof_single_failure_does_not_arm_lesson(at: ActTruth) -> None:
    at.ledger.record(
        agent_id="aetheria",
        kind="timeout",
        summary="generate_image FAILED — timed out",
        ok=False,
        tool="generate_image",
    )
    assert lessons_from_events(
        at.ledger.recent("aetheria", limit=10, failures_only=True)
    ) == []
    assert lessons_brief("aetheria") == ""


def test_proof_in_band_lesson_on_tool_result_after_streak(at: ActTruth) -> None:
    """Same-turn anti-loop: second identical FAIL returns acttruth_lesson text."""
    at.ledger.record(
        agent_id="aetheria",
        kind="timeout",
        summary="generate_image FAILED — timed out after 180s",
        ok=False,
        tool="generate_image",
    )
    # Simulate the just-recorded second failure already in the ledger
    at.ledger.record(
        agent_id="aetheria",
        kind="timeout",
        summary="generate_image FAILED — timed out after 180s",
        ok=False,
        tool="generate_image",
    )
    lesson = maybe_lesson_for_tool_result(
        "aetheria",
        tool="generate_image",
        ok=False,
        error="ComfyUI generation timed out after 180s",
    )
    assert lesson is not None
    assert "generate_image" in lesson
    assert "Do NOT repeat" in lesson or "LESSON" in lesson


def test_proof_classify_error_groups_timeouts() -> None:
    assert classify_error("ComfyUI generation timed out after 180s") == "timeout"
    assert classify_error("timed out") == "timeout"
    assert classify_error("Connection refused") == "unreachable"


# ─── Claim 4: lessons reach AgentLoop tool payload ───────────────────────────


def test_proof_agent_loop_tool_result_carries_lesson(
    at: ActTruth, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from soveryn.agents.loop import AgentLoop
    from soveryn.memory.conversation_store import ConversationStore
    from soveryn.platform.tools.registry import ToolRegistry, ToolSpec

    # Prime streak
    for _ in range(2):
        at.ledger.record(
            agent_id="aetheria",
            kind="timeout",
            summary="flaky FAILED — timed out after 180s",
            ok=False,
            tool="flaky",
        )

    def boom(_args):
        raise TimeoutError("flaky timed out after 180s")

    reg = ToolRegistry(
        active_agents=("aetheria",),
        audit_hook=lambda e: record_tool_audit(
            agent=e.agent,
            tool_name=e.tool_name,
            args=dict(e.args or {}),
            ok=e.ok,
            result=e.result,
            error=e.error,
            acttruth=at,
        ),
    )
    reg.register(
        ToolSpec(
            name="flaky",
            owner="aetheria",
            schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=boom,
            description="always times out",
        )
    )
    conv = ConversationStore(tmp_path / "conv.db")
    loop = AgentLoop("aetheria", conv, tool_registry=reg)
    msg = loop._tool_result_message(
        {"id": "call_1", "function": {"name": "flaky", "arguments": "{}"}},
        session_id=None,
    )
    payload = json.loads(msg.content or "{}")
    assert "error" in payload or "Timeout" in str(payload)
    assert "acttruth_lesson" in payload
    assert "flaky" in payload["acttruth_lesson"]


# ─── Claim 5: crew surface includes Kernel ───────────────────────────────────


def test_proof_crew_includes_kernel(at: ActTruth) -> None:
    assert "kernel" in CREW_AGENTS
    assert "eve" in CREW_AGENTS
    at.ledger.record(
        agent_id="kernel",
        kind="tool_ok",
        summary="list_dir ok",
        ok=True,
        tool="list_dir",
    )
    snap = crew_status(limit=3)
    assert "kernel" in snap["agents"]
    assert snap["agents"]["kernel"]["recent"]


# ─── Claim 6: earned-keep is honest about theater ────────────────────────────


def test_proof_earned_keep_penalizes_no_durable_delta() -> None:
    from soveryn.platform.acttruth.earned_keep import score_unprompted_act

    theater = score_unprompted_act(durable_delta=False, ledger_honest=True)
    real = score_unprompted_act(durable_delta=True, ledger_honest=True, human_kept=True)
    assert theater.score < real.score
    assert score_unprompted_act(durable_delta=True, ledger_honest=False).score == 0.0


# ─── Claim 7: honest stats / shareable proof ─────────────────────────────────


def test_proof_stats_from_ledger_only(at: ActTruth, monkeypatch: pytest.MonkeyPatch) -> None:
    from soveryn.platform.acttruth import proof as proof_mod

    monkeypatch.setattr(proof_mod, "get_acttruth", lambda: at)
    at.ledger.record(
        agent_id="aetheria", kind="tool_ok", summary="search ok", ok=True, tool="search",
    )
    at.ledger.record(
        agent_id="aetheria", kind="timeout", summary="generate_image FAILED — timed out",
        ok=False, tool="generate_image",
    )
    at.ledger.record(
        agent_id="aetheria", kind="timeout", summary="generate_image FAILED — timed out",
        ok=False, tool="generate_image",
    )
    p = proof_mod.collect_proof(window_hours=24, include_pytest=False)
    assert p.total_events >= 3
    assert p.total_fail >= 2
    assert p.total_timeouts >= 2
    assert p.lessons_armed >= 1
    assert p.fail_rate() is not None
    post = proof_mod.format_proof_post(p, style="x")
    assert "ActTruth proof" in post
    assert "FAIL" in post
    assert "acttruth.com" in post
    # honesty: must not invent success theater
    assert "100% success" not in post.lower()
    assert "guaranteed" not in post.lower()


def test_proof_post_markdown_has_table(at: ActTruth, monkeypatch: pytest.MonkeyPatch) -> None:
    from soveryn.platform.acttruth import proof as proof_mod

    monkeypatch.setattr(proof_mod, "get_acttruth", lambda: at)
    at.ledger.record(
        agent_id="vett", kind="tool_ok", summary="patrol ok", ok=True, tool="read_patrol_sources",
    )
    p = proof_mod.collect_proof(window_hours=24, include_pytest=False)
    md = proof_mod.format_proof_post(p, style="markdown")
    assert "| FAIL |" in md or "| FAIL |" in md.replace("fail", "FAIL")
    assert "No invented uplift" in md or "ledger only" in md.lower()
