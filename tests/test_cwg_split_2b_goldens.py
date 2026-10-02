"""Goldens captured on unmodified main for CWG split step 2b.

Commit these files BEFORE the seam refactor. After the refactor they must
still match (production behavior identical). Rewrite with
``SOVERYN_UPDATE_GOLDEN=1 pytest tests/test_cwg_split_2b_goldens.py``.

Persona / skill / routine lookups are redirected to a tmp data root
(see ``_hermetic_cwg_2b_data``). Eve and Forge skill indexes come from
``tests/fixtures/cwg_split_2b/skills/``, not the live checkout ``data/``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.app.services import public_agents as pa
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore
from soveryn.paths import SoverynPaths

from tests.helpers.cwg_2b_capture import (
    GOLDEN_DIR,
    assembled_personas,
    email_identities_snapshot,
    path_formulas,
    public_agents_payload_shape,
    resolved_cwg_paths,
    routines_and_skills_snapshot,
    stabilize_tool_schemas,
    tool_schemas_from_app,
    write_json,
    write_text,
)
from tests.helpers.hermetic import isolate_data_root


def _update() -> bool:
    return os.environ.get("SOVERYN_UPDATE_GOLDEN", "").strip() == "1"


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _hermetic_cwg_2b_data(tmp_path, monkeypatch) -> Path:
    """Every 2b golden must read personas/skills/routines from tmp, not data/."""
    return isolate_data_root(tmp_path, monkeypatch, seed_skill_fixtures=True)


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
        "2b golden fixture memory",
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


def test_persona_goldens_match_main():
    """Eve + Aetheria assembled persona text — captured on main before 2b."""
    texts = assembled_personas()
    for agent, body in texts.items():
        path = GOLDEN_DIR / "personas" / f"{agent}.md"
        if _update():
            write_text(path, body)
            continue
        assert path.is_file(), f"missing persona golden {path}"
        assert body == path.read_text(encoding="utf-8")


def test_goldens_ignore_repo_data_persona_override(tmp_path):
    """A local data/memory/personas/eve.md must not change 2b goldens."""
    from soveryn.agents.personas import persona_override_path
    from soveryn.config.loader import load_env_config

    tmp = tmp_path.resolve()
    cfg = load_env_config()
    override = persona_override_path("eve")
    assert cfg.data_root.resolve().is_relative_to(tmp)
    assert cfg.skills_dir.resolve().is_relative_to(tmp)
    assert override.resolve().is_relative_to(tmp)
    assert not override.is_file()

    repo_dir = Path(__file__).resolve().parents[1] / "data" / "memory" / "personas"
    repo_dir.mkdir(parents=True, exist_ok=True)
    junk = repo_dir / "eve.md"
    previous = junk.read_text(encoding="utf-8") if junk.is_file() else None
    try:
        junk.write_text(
            "# JUNK local Eve override — goldens must ignore this\n",
            encoding="utf-8",
        )
        texts = assembled_personas()
        expected = (GOLDEN_DIR / "personas" / "eve.md").read_text(encoding="utf-8")
        assert texts["eve"] == expected
        assert "JUNK local Eve override" not in texts["eve"]
        snap = routines_and_skills_snapshot()
        assert snap == _read_json(GOLDEN_DIR / "routines_and_skills.json")
    finally:
        if previous is None:
            junk.unlink(missing_ok=True)
        else:
            junk.write_text(previous, encoding="utf-8")


def test_tool_schema_golden(
    tmp_path,
    monkeypatch,
    fake_souls_dir,
    fake_pinned,
    recall_lattice_path,
):
    """Every ToolSpec name/description/parameter schema per owner."""
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
    loops = app.extensions["soveryn"]["agent_loops"]
    assert isinstance(loops, dict)
    assert all(isinstance(loop, AgentLoop) for loop in loops.values())

    schemas = tool_schemas_from_app(app)
    path = GOLDEN_DIR / "tool_schemas.json"
    if _update():
        write_json(path, schemas)
        return
    assert path.is_file(), f"missing tool schema golden {path}"
    expected = _read_json(path)
    assert stabilize_tool_schemas(schemas) == stabilize_tool_schemas(expected)

    # Spotlight the tools the 2b prompt names — dest/book enums must not drift.
    eve = {row["name"]: row for row in schemas["eve"]}
    for name in ("file_away", "ledger_ingest", "eve_photo_inbox", "make_collage"):
        assert name in eve, name
    ledger_enum = eve["ledger_ingest"]["schema"]["properties"]["book"]["enum"]
    assert ledger_enum == ["soveryn", "cwg", "auto"]


def test_path_formula_golden():
    """Relative CWG path formulas captured from main."""
    formulas = path_formulas()
    path = GOLDEN_DIR / "cwg_path_formulas.json"
    if _update():
        write_json(path, formulas)
        return
    assert path.is_file()
    assert formulas == _read_json(path)


def test_path_parity_under_fake_soveryn_root(tmp_path, monkeypatch):
    """Every CWG path under a fake SOVERYN_ROOT matches the main formulas."""
    root = tmp_path / "checkout"
    data = root / "data"
    data.mkdir(parents=True)
    monkeypatch.setenv("SOVERYN_ROOT", str(root))
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(data))
    home = Path.home()

    resolved = resolved_cwg_paths(root=root, data_root=data, home=home)
    formulas = path_formulas()
    path = GOLDEN_DIR / "cwg_path_formulas.json"
    if _update():
        write_json(path, formulas)
    else:
        assert formulas == _read_json(path)

    assert resolved["soveryn_root"] == str(SoverynPaths.root())
    assert resolved["cwg_csv"] == str(root / formulas["cwg_csv"])
    assert resolved["cwg_evidence"] == str(root / formulas["cwg_evidence"])
    assert resolved["cwg_ig"] == str(home / "Desktop" / "CWG-Instagram")
    assert resolved["cwg_insurance"] == str(root / formulas["cwg_insurance"])
    assert resolved["cwg_licenses"] == str(root / formulas["cwg_licenses"])
    assert resolved["cwg_vehicles"] == str(root / formulas["cwg_vehicles"])
    assert resolved["cwg_contracts"] == str(root / formulas["cwg_contracts"])
    assert resolved["lead_watch_state"] == str(root / formulas["lead_watch_state"])
    assert resolved["gbp_token_dir"] == str(data / "gbp")
    assert resolved["gcal_token_dir"] == str(data / "gcal")
    assert resolved["photo_inbox"] == str(home / "Desktop" / "CWG-Instagram")
    # IG profile still resolves via the checkout that imported instagram_desk
    # (SoverynPaths is not used there yet). Lock the filename, not the host.
    assert resolved["ig_profile_dir"].endswith("/data/eve_ig_profile")
    for key in (
        "cwg_ig",
        "cwg_evidence",
        "cwg_insurance",
        "cwg_licenses",
        "cwg_vehicles",
        "cwg_contracts",
    ):
        assert key in resolved["file_away_buckets"]


def test_email_identities_golden():
    snap = email_identities_snapshot()
    path = GOLDEN_DIR / "email_identities.json"
    if _update():
        write_json(path, snap)
        return
    assert path.is_file()
    assert snap == _read_json(path)


def test_routines_and_skills_golden():
    snap = routines_and_skills_snapshot()
    path = GOLDEN_DIR / "routines_and_skills.json"
    if _update():
        write_json(path, snap)
        return
    assert path.is_file()
    assert snap == _read_json(path)
    assert "pond_academy_watch" in snap["routine_ids"]
    assert "eve_product_advertise" in snap["routine_ids"]
    assert "cwg-crm" in snap["skill_index"].get("eve", "")


def test_public_agents_payload_golden():
    """ /api/system public-agents + CRM payload shape with fakes."""
    bundle = {
        "agents": {
            "8200": {
                "summary": {
                    "enabled": True,
                    "conversations_today": 1,
                    "conversations_total": 4,
                    "turns_today": 2,
                    "leads_captured": 1,
                    "last_activity": "2026-10-02T12:00:00",
                    "recent": [
                        {
                            "ts": "2026-10-02T12:00:00",
                            "preview": "hello",
                            "captured": False,
                        }
                    ],
                },
                "health": {
                    "ok": True,
                    "model_ok": True,
                    "model": "lightning-30b",
                    "enabled": True,
                },
                "error": None,
            },
            "8400": {
                "summary": {
                    "enabled": True,
                    "conversations_today": 0,
                    "conversations_total": 1,
                    "turns_today": 0,
                    "leads_captured": 0,
                    "last_activity": None,
                    "recent": [],
                },
                "health": {"ok": True, "model_ok": True, "model": "x", "enabled": True},
                "error": None,
            },
            "8500": {
                "summary": {
                    "enabled": True,
                    "conversations_today": 0,
                    "conversations_total": 1,
                    "turns_today": 0,
                    "leads_captured": 0,
                    "last_activity": None,
                    "recent": [],
                },
                "health": {"ok": True, "model_ok": True, "model": "x", "enabled": True},
                "error": None,
            },
        },
        "waitlist": {"ok": False},
    }
    crm = {
        "ok": True,
        "leads_total": 3,
        "leads_new": 2,
        "leads_today": 1,
        "open": "https://crm.pondwright.com/",
        "label": "PondWright CRM",
        "recent": [
            {
                "name": "Lead A",
                "status": "new",
                "interest": "cleanout",
                "created_at": "2026-10-02T10:00:00Z",
                "phone": "",
            }
        ],
    }
    with patch.object(pa, "_ssh_json_bundle", return_value=bundle):
        with patch.object(pa, "_crm_pipeline", return_value=crm):
            with patch.object(pa, "_cache", {"at": 0.0, "payload": None}):
                payload = pa.get_public_agents(force=True)
    shaped = public_agents_payload_shape(payload)
    path = GOLDEN_DIR / "public_agents_payload.json"
    if _update():
        write_json(path, shaped)
        return
    assert path.is_file()
    assert shaped == _read_json(path)
    assert [a["id"] for a in shaped["agents"]] == ["pondwright", "seneca", "atticus"]
    assert shaped["crm"]["label"] == "PondWright CRM"
    assert shaped["intake"]["crm_open"] == "https://crm.pondwright.com/"
