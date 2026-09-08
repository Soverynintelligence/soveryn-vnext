"""Eve file_away: Downloads/Desktop → named buckets, no free mv."""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.platform.intake.file_away import file_away
from soveryn.platform.intake.tools import build_file_away_tool, register_qr_tools
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


def test_file_away_moves_into_bucket(tmp_path: Path):
    src_root = tmp_path / "Downloads"
    src_root.mkdir()
    src = src_root / "shot.jpg"
    src.write_bytes(b"jpeg")
    dest = tmp_path / "CWG-Instagram"
    out = file_away(
        src,
        "cwg_ig",
        src_roots=(src_root,),
        buckets={"cwg_ig": dest},
    )
    assert out["ok"] is True
    assert not src.exists()
    assert (dest / "shot.jpg").is_file()


def test_file_away_rejects_outside_downloads(tmp_path: Path):
    outsider = tmp_path / "secret.txt"
    outsider.write_text("no")
    dest = tmp_path / "bucket"
    out = file_away(
        outsider,
        "pictures",
        src_roots=(tmp_path / "Downloads",),
        buckets={"pictures": dest},
    )
    assert out["ok"] is False
    assert out["miss"] == "outside_source"
    assert outsider.is_file()


def test_file_away_models_gguf_only(tmp_path: Path):
    src_root = tmp_path / "Downloads"
    src_root.mkdir()
    pdf = src_root / "note.pdf"
    pdf.write_bytes(b"%PDF")
    out = file_away(
        pdf,
        "models",
        src_roots=(src_root,),
        buckets={"models": tmp_path / "GGUF"},
    )
    assert out["ok"] is False
    assert out["miss"] == "not_a_model"
    assert pdf.is_file()


def test_file_away_refuses_overwrite(tmp_path: Path):
    src_root = tmp_path / "Downloads"
    src_root.mkdir()
    dest = tmp_path / "pictures"
    dest.mkdir()
    (dest / "a.jpg").write_bytes(b"old")
    src = src_root / "a.jpg"
    src.write_bytes(b"new")
    out = file_away(
        src,
        "pictures",
        src_roots=(src_root,),
        buckets={"pictures": dest},
    )
    assert out["ok"] is False
    assert out["miss"] == "already_there"
    assert src.is_file()
    assert (dest / "a.jpg").read_bytes() == b"old"


def test_file_away_tool_requires_path(tmp_path: Path):
    tool = build_file_away_tool(owner_agent="eve")
    with pytest.raises(ToolArgError):
        tool.handler({"dest": "pictures"})


def test_file_away_registered_eve_only():
    reg = ToolRegistry(
        active_agents=("eve", "kernel", "aetheria"),
        audit_hook=lambda _e: None,
    )
    register_qr_tools(reg, owner_agent="eve")
    eve = {t.name for t in reg.iter_tools_for_agent("eve")}
    assert "file_away" in eve
    assert "file_away" not in {t.name for t in reg.iter_tools_for_agent("kernel")}
    assert "file_away" not in {t.name for t in reg.iter_tools_for_agent("aetheria")}
