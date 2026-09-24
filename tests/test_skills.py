"""Citizen skills loader + recall_skill tool (Kernel Slice A, finished)."""
from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.agents.recall_skill_tool import build_recall_skill_tool
from soveryn.agents.skills import SkillNameError, get_skill_index, load_skill
from soveryn.config.loader import load_env_config
from soveryn.memory.conversation_store import ConversationStore
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.platform.tools.registry import ToolRegistry


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    eve = root / "eve"
    eve.mkdir(parents=True)
    (eve / "_index.md").write_text(
        "- cwg-caption-style: CWG pond post captions in Jon's voice\n"
        "- draft-held-pile: park drafts for Jon before send\n",
        encoding="utf-8",
    )
    (eve / "cwg-caption-style.md").write_text(
        "# CWG caption style\n\n"
        "- id: cwg-caption-style\n"
        "- owner: eve\n"
        "- when: composing Carolina Water Gardens social captions\n\n"
        "## Procedure\n"
        "1. Lead with the water feature, not the gear.\n"
        "2. One concrete sensory detail.\n"
        "3. Soft CTA — visit / ask, no hype.\n\n"
        "## Verify\n"
        "- Sounds like Jon, not an ad bot.\n",
        encoding="utf-8",
    )
    return root


def test_empty_skills_dir_returns_empty(tmp_path: Path):
    assert get_skill_index("aetheria", skills_dir=tmp_path) == ""
    assert load_skill("aetheria", "anything", skills_dir=tmp_path) == ""


def test_get_skill_index_and_load_body(skills_root: Path):
    idx = get_skill_index("eve", skills_dir=skills_root)
    assert "cwg-caption-style" in idx
    body = load_skill("eve", "cwg-caption-style", skills_dir=skills_root)
    assert "Lead with the water feature" in body
    assert load_skill("eve", "missing-skill", skills_dir=skills_root) == ""


def test_path_traversal_and_unknown_agent_rejected(skills_root: Path):
    with pytest.raises(SkillNameError):
        load_skill("eve", "../passwd", skills_dir=skills_root)
    with pytest.raises(SkillNameError):
        load_skill("eve", "has spaces", skills_dir=skills_root)
    with pytest.raises(SkillNameError):
        get_skill_index("not_a_citizen", skills_dir=skills_root)
    with pytest.raises(SkillNameError):
        load_skill("scout", "x", skills_dir=skills_root)  # retired


def test_agent_cannot_read_other_citizens_skill_file(skills_root: Path):
    # File only under eve/ — aetheria index empty, load empty (no cross-read).
    assert get_skill_index("aetheria", skills_dir=skills_root) == ""
    assert load_skill("aetheria", "cwg-caption-style", skills_dir=skills_root) == ""


def test_recall_skill_tool_ok_and_missing(skills_root: Path):
    tool = build_recall_skill_tool(skills_dir=skills_root, owner_agent="eve")
    assert tool.name == "recall_skill"
    assert tool.owner == "eve"
    ok = tool.handler({"name": "cwg-caption-style"})
    assert ok["ok"] is True
    assert "Lead with the water feature" in ok["content"]
    miss = tool.handler({"name": "nope"})
    assert miss["ok"] is False
    assert miss["error"] == "skill_missing"
    bad = tool.handler({"name": "../x"})
    assert bad["ok"] is False
    assert bad["error"] == "skill_name_invalid"


def test_loop_prelude_includes_labeled_skills_index(skills_root: Path, tmp_path: Path, fake_chat):
    captured: list = []

    def capture_chat(request, server, timeout=60.0):
        captured.append(request)
        return ChatResponse(content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})

    conv = ConversationStore(tmp_path / "c.db")
    sid = conv.new_session("eve", title="skills-prelude")
    loop = AgentLoop(
        "eve",
        conv,
        chat_fn=capture_chat,
        soul_text="",  # skip soul file
        skills_dir=skills_root,
        max_tool_rounds=0,
    )
    loop.process_message(sid, "hi")
    assert captured
    systems = [m.content for m in captured[0].messages if m.role == "system"]
    joined = "\n".join(str(c) for c in systems)
    assert "PROCEDURAL SKILLS" in joined
    assert "cwg-caption-style" in joined
    assert "recall_skill" in joined


def test_loop_skips_skills_block_when_no_index(tmp_path: Path, fake_chat):
    captured: list = []

    def capture_chat(request, server, timeout=60.0):
        captured.append(request)
        return ChatResponse(content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})

    conv = ConversationStore(tmp_path / "c.db")
    sid = conv.new_session("eve", title="no-skills")
    loop = AgentLoop(
        "eve",
        conv,
        chat_fn=capture_chat,
        soul_text="",
        skills_dir=tmp_path / "empty_skills",
        max_tool_rounds=0,
    )
    loop.process_message(sid, "hi")
    systems = [m.content for m in captured[0].messages if m.role == "system"]
    joined = "\n".join(str(c) for c in systems)
    assert "PROCEDURAL SKILLS" not in joined


def test_env_skills_dir_default_under_memory():
    cfg = load_env_config()
    assert cfg.skills_dir.name == "skills"
    assert cfg.skills_dir.parent.name == "memory"


def test_registry_registers_recall_per_agent(skills_root: Path):
    reg = ToolRegistry()
    for agent in ("aetheria", "eve", "vett"):
        reg.register(build_recall_skill_tool(skills_dir=skills_root, owner_agent=agent))
    eve_tools = [t.name for t in reg.iter_tools_for_agent("eve")]
    assert "recall_skill" in eve_tools
    # Owner-scoped: invoking via eve tool only sees eve files
    eve_tool = next(t for t in reg.iter_tools_for_agent("eve") if t.name == "recall_skill")
    assert eve_tool.handler({"name": "cwg-caption-style"})["ok"] is True
