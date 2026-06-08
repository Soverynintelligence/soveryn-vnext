"""Tests for Aetheria's personal-file browser tools.

Path-safety checks use tmp_path-rooted overrides of AETHERIA_CONTENT_ROOTS
so production paths (~/Pictures etc.) aren't touched by the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.agents.aetheria.tools import personal_files as pf
from soveryn.platform.tools.registry import ToolArgError


# ─── resolve_within_content_roots ─────────────────────────────────────────────


def test_resolve_accepts_absolute_path_under_root(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (tmp_path,))
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"x")
    result = pf.resolve_within_content_roots(str(f))
    assert result == f


def test_resolve_rejects_relative_path(monkeypatch, tmp_path):
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (tmp_path,))
    with pytest.raises(pf.PathOutOfContentRootsError, match="absolute"):
        pf.resolve_within_content_roots("relative/photo.jpg")


def test_resolve_rejects_traversal_segment(monkeypatch, tmp_path):
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (tmp_path,))
    with pytest.raises(pf.PathOutOfContentRootsError, match="traversal"):
        pf.resolve_within_content_roots("/tmp/../etc/passwd")


def test_resolve_rejects_path_outside_all_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (tmp_path,))
    with pytest.raises(pf.PathOutOfContentRootsError, match="outside"):
        pf.resolve_within_content_roots("/etc/passwd")


def test_resolve_rejects_empty_string():
    with pytest.raises(pf.PathOutOfContentRootsError, match="non-empty"):
        pf.resolve_within_content_roots("")


# ─── list_personal_files ───────────────────────────────────────────────────


def test_list_with_no_path_returns_roots_summary(monkeypatch, tmp_path):
    pics = tmp_path / "Pictures"; pics.mkdir()
    docs = tmp_path / "Documents"; docs.mkdir()
    (pics / "a.jpg").write_bytes(b"x")
    (pics / "b.png").write_bytes(b"x")
    (docs / "notes.md").write_text("x")
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (pics, docs))

    tool = pf.build_list_personal_files_tool()
    result = tool.handler({})
    assert "roots" in result
    pics_summary = [r for r in result["roots"] if r["root"] == str(pics)][0]
    docs_summary = [r for r in result["roots"] if r["root"] == str(docs)][0]
    assert pics_summary["entry_count"] == 2
    assert docs_summary["entry_count"] == 1
    assert pics_summary["exists"]


def test_list_with_path_returns_entries(monkeypatch, tmp_path):
    pics = tmp_path / "Pictures"; pics.mkdir()
    (pics / "soveryn-logo.png").write_bytes(b"x" * 512)
    (pics / "vacation.jpg").write_bytes(b"x" * 1024)
    subdir = pics / "screenshots"; subdir.mkdir()
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (pics,))

    tool = pf.build_list_personal_files_tool()
    result = tool.handler({"path": str(pics)})
    names = {e["name"] for e in result["entries"]}
    assert names == {"soveryn-logo.png", "vacation.jpg", "screenshots"}
    by_name = {e["name"]: e for e in result["entries"]}
    assert by_name["soveryn-logo.png"]["kind"] == "file"
    assert by_name["soveryn-logo.png"]["size_bytes"] == 512
    assert by_name["screenshots"]["kind"] == "directory"
    assert by_name["screenshots"]["size_bytes"] is None
    assert result["truncated"] is False


def test_list_rejects_path_outside_roots(monkeypatch, tmp_path):
    pics = tmp_path / "Pictures"; pics.mkdir()
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (pics,))
    tool = pf.build_list_personal_files_tool()
    with pytest.raises(ToolArgError, match="outside"):
        tool.handler({"path": "/etc"})


def test_list_rejects_nonexistent_path(monkeypatch, tmp_path):
    pics = tmp_path / "Pictures"; pics.mkdir()
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (pics,))
    tool = pf.build_list_personal_files_tool()
    with pytest.raises(ToolArgError, match="does not exist"):
        tool.handler({"path": str(pics / "ghost-dir")})


def test_list_truncates_at_max_entries(monkeypatch, tmp_path):
    pics = tmp_path / "Pictures"; pics.mkdir()
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (pics,))
    monkeypatch.setattr(pf, "LIST_MAX_ENTRIES", 5)
    for i in range(10):
        (pics / f"img-{i}.jpg").write_bytes(b"x")
    tool = pf.build_list_personal_files_tool()
    result = tool.handler({"path": str(pics)})
    assert result["truncated"] is True
    assert result["count"] == 5


# ─── read_personal_file ─────────────────────────────────────────────────────


def test_read_text_file_returns_content(monkeypatch, tmp_path):
    docs = tmp_path / "Documents"; docs.mkdir()
    notes = docs / "notes.md"
    notes.write_text("# Hello Aetheria\n\nThis is a test note.\n")
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (docs,))
    tool = pf.build_read_personal_file_tool()
    result = tool.handler({"path": str(notes)})
    assert result["kind"] == "text"
    assert "Hello Aetheria" in result["content"]
    assert result["truncated"] is False


def test_read_binary_file_returns_metadata_stub(monkeypatch, tmp_path):
    """Image / PDF / audio bodies are NOT loaded — Aetheria gets a
    metadata stub and passes the path to signal_send if she wants to
    share it. Keeps her context clean."""
    pics = tmp_path / "Pictures"; pics.mkdir()
    logo = pics / "soveryn-logo.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 4096)
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (pics,))
    tool = pf.build_read_personal_file_tool()
    result = tool.handler({"path": str(logo)})
    assert result["kind"] == "binary"
    assert result["extension"] == ".png"
    assert result["content"] is None
    assert result["size_bytes"] == 4104
    assert "signal_send" in result["note"]


def test_read_truncates_large_text_file(monkeypatch, tmp_path):
    docs = tmp_path / "Documents"; docs.mkdir()
    big = docs / "big.txt"
    big.write_bytes(b"x" * (300 * 1024))  # > READ_FILE_MAX_BYTES
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (docs,))
    tool = pf.build_read_personal_file_tool()
    result = tool.handler({"path": str(big)})
    assert result["truncated"] is True
    assert len(result["content"].encode()) == pf.READ_FILE_MAX_BYTES


def test_read_rejects_path_outside_roots(monkeypatch, tmp_path):
    docs = tmp_path / "Documents"; docs.mkdir()
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (docs,))
    tool = pf.build_read_personal_file_tool()
    with pytest.raises(ToolArgError, match="outside"):
        tool.handler({"path": "/etc/passwd"})


def test_read_rejects_directory(monkeypatch, tmp_path):
    docs = tmp_path / "Documents"; docs.mkdir()
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (docs,))
    tool = pf.build_read_personal_file_tool()
    with pytest.raises(ToolArgError, match="not a regular file"):
        tool.handler({"path": str(docs)})


def test_read_rejects_nonexistent(monkeypatch, tmp_path):
    docs = tmp_path / "Documents"; docs.mkdir()
    monkeypatch.setattr(pf, "AETHERIA_CONTENT_ROOTS", (docs,))
    tool = pf.build_read_personal_file_tool()
    with pytest.raises(ToolArgError, match="does not exist"):
        tool.handler({"path": str(docs / "ghost.md")})


# ─── register_personal_files_tools ─────────────────────────────────────────


def test_register_personal_files_tools_registers_both():
    from soveryn.platform.tools.registry import ToolRegistry
    registry = ToolRegistry()
    pf.register_personal_files_tools(registry, owner_agent="aetheria")
    names = {t.name for t in registry.iter_tools_for_agent("aetheria")}
    assert "list_personal_files" in names
    assert "read_personal_file" in names
