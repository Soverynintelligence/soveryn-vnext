"""Skills routing integrity must hold: every skill body is routed by its
agent's _index.md, every index reference has a body.

The index is the tiny always-on prelude layer (soveryn.agents.skills
get_skill_index); bodies load on demand via load_skill. A body missing
from the index is a silent capability loss — the model never learns the
skill exists. An index entry without a body is a ghost — load_skill
returns "" and the model follows nothing.

Adopted from steipete/agent-scripts validate-skills (2026-09-29), adapted
to the house format. The .git/hooks pre-commit runs the same validator
when skills files are staged; this test makes it survive hook loss too.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "scripts" / "validate_skills.py"


def test_skills_routing_integrity():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), "--quiet"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        "skills routing broken:\n" + result.stdout + result.stderr
    )


def test_validator_catches_an_unrouted_body(tmp_path, monkeypatch):
    """Not self-defanging: the validator must actually fail on the bug it
    exists to catch — a body file with no index line."""
    agent_dir = tmp_path / "testagent"
    agent_dir.mkdir()
    (agent_dir / "ghost-skill.md").write_text("# ghost\nbody\n")

    import importlib.util

    spec = importlib.util.spec_from_file_location("validate_skills", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path)

    problems = mod.problems_for_agent(agent_dir)
    assert any("ghost-skill" in p and "not in _index.md" in p for p in problems)


def test_validator_catches_a_ghost_index_entry(tmp_path, monkeypatch):
    """And the other direction: an index entry with no body file."""
    agent_dir = tmp_path / "testagent"
    agent_dir.mkdir()
    (agent_dir / "_index.md").write_text(
        "skills: `ghost.md` — does not exist\n"
    )

    import importlib.util

    spec = importlib.util.spec_from_file_location("validate_skills", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path)

    problems = mod.problems_for_agent(agent_dir)
    assert any("no body file exists" in p for p in problems)
