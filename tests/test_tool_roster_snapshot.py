"""Golden snapshot of every registered tool and its Approval Gate status.

Captures ``{owner: [[tool, requires_approval(direct), requires_approval(automation)]]}``.
The file is generated on ``main`` first so later plugin PRs can prove they
are roster-neutral (or show an intentional gate flip).

Rewrite the golden with ``SOVERYN_UPDATE_GOLDEN=1 pytest tests/test_tool_roster_snapshot.py``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from flask import Flask

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.citizens.connectors import requires_approval
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore

GOLDEN = Path(__file__).resolve().parent / "golden" / "tool_roster.json"


@pytest.fixture
def fake_souls_dir(tmp_path) -> Path:
    souls_dir = tmp_path / "souls"
    souls_dir.mkdir()
    for agent in ACTIVE_AGENTS:
        (souls_dir / f"{agent}.md").write_text(f"# {agent}\n", encoding="utf-8")
    return souls_dir


@pytest.fixture
def fake_pinned(tmp_path) -> Path:
    pinned = tmp_path / "pinned.md"
    pinned.write_text("# Pinned relationship substrate\n", encoding="utf-8")
    return pinned


@pytest.fixture
def recall_lattice_path(tmp_path) -> Path:
    store = LatticeStore(tmp_path / "recall_lattice.db")
    store.write_node(
        "aetheria",
        "tool roster snapshot fixture memory",
        provenance={
            "cls": "witnessed",
            "source": "test",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    return tmp_path / "recall_lattice.db"


def _disable_background_workers(monkeypatch) -> None:
    original_init = Flask.__init__

    def _init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.config["SOVERYN_START_MESSENGER_WORKER"] = False
        self.config["SOVERYN_START_DELEGATION_WORKER"] = False
        self.config["SOVERYN_START_CITIZENS_WORKER"] = False
        self.config["SOVERYN_START_LEAD_WATCH"] = False

    monkeypatch.setattr(Flask, "__init__", _init)


def _build_roster(app: Flask) -> dict[str, list[list]]:
    registry = app.extensions["soveryn"]["tool_registry"]
    assert registry is not None
    by_owner: dict[str, list[str]] = {}
    for spec in registry._tools.values():
        by_owner.setdefault(spec.owner, []).append(spec.name)
    roster: dict[str, list[list]] = {}
    for owner in sorted(by_owner):
        rows: list[list] = []
        for name in sorted(set(by_owner[owner])):
            rows.append(
                [
                    name,
                    bool(requires_approval(name, source="direct")),
                    bool(requires_approval(name, source="automation")),
                ]
            )
        roster[owner] = rows
    return roster


def test_tool_roster_matches_golden(
    tmp_path,
    monkeypatch,
    fake_souls_dir,
    fake_pinned,
    recall_lattice_path,
):
    """Registered tools + gate flags must match the committed golden."""
    _disable_background_workers(monkeypatch)
    data_root = tmp_path / "data"
    data_root.mkdir()
    monkeypatch.setenv("SOVERYN_ROOT", str(tmp_path))
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(data_root))
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_LATTICE_DB", str(recall_lattice_path))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(recall_lattice_path))
    monkeypatch.setenv("SOVERYN_START_DELEGATION_WORKER", "false")

    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    # Loops exist (production build path) — roster is taken from the registry.
    loops = app.extensions["soveryn"]["agent_loops"]
    assert isinstance(loops, dict)
    assert all(isinstance(loop, AgentLoop) for loop in loops.values())

    roster = _build_roster(app)
    if os.environ.get("SOVERYN_UPDATE_GOLDEN", "").strip() == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(roster, indent=2) + "\n", encoding="utf-8")
        return

    assert GOLDEN.is_file(), (
        f"missing golden {GOLDEN}; generate with "
        "SOVERYN_UPDATE_GOLDEN=1 pytest tests/test_tool_roster_snapshot.py"
    )
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert roster == expected
