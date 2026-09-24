"""Tests for soveryn.agents.souls — read-only per-agent soul.md loader."""

import pytest

from soveryn.agents.souls import (
    SoulMissingError, SoulNameError, get_soul, get_soul_origin,
)


@pytest.fixture
def souls_dir(tmp_path):
    d = tmp_path / "souls"
    d.mkdir()
    (d / "aetheria.md").write_text("# Aetheria\n\nFirst intelligence.\n", encoding="utf-8")
    (d / "aetheria.origin.md").write_text(
        "# HOW WE BECAME SOVERYN\n\nOrigin essay body.\n", encoding="utf-8",
    )
    (d / "vett.md").write_text("# Vett\n\nVerify or say nothing.\n", encoding="utf-8")
    (d / "scotty.md").write_text("# Scotty\n\nBounded execution.\n", encoding="utf-8")
    return d


def test_get_soul_aetheria_reads_file(souls_dir):
    text = get_soul("aetheria", souls_dir=souls_dir)
    assert "Aetheria" in text
    assert "First intelligence" in text
    # Hot path excludes origin essay (PR5)
    assert "Origin essay body" not in text


def test_get_soul_include_origin_appends_essay(souls_dir):
    text = get_soul("aetheria", souls_dir=souls_dir, include_origin=True)
    assert "First intelligence" in text
    assert "Origin essay body" in text


def test_get_soul_origin_reads_origin_file(souls_dir):
    text = get_soul_origin("aetheria", souls_dir=souls_dir)
    assert "HOW WE BECAME SOVERYN" in text
    assert "Origin essay body" in text


def test_get_soul_origin_missing_returns_empty(souls_dir):
    (souls_dir / "kernel.md").write_text("# Kernel\n", encoding="utf-8")
    assert get_soul_origin("kernel", souls_dir=souls_dir) == ""


def test_get_soul_rejects_folded_vett_and_scotty(souls_dir):
    with pytest.raises(SoulNameError):
        get_soul("vett", souls_dir=souls_dir)
    with pytest.raises(SoulNameError):
        get_soul("scotty", souls_dir=souls_dir)


def test_get_soul_normalizes_agent_name_case(souls_dir):
    a = get_soul("AETHERIA", souls_dir=souls_dir)
    b = get_soul("  aetheria  ", souls_dir=souls_dir)
    assert a == b


def test_get_soul_missing_raises_for_active_agent_by_default(tmp_path):
    empty = tmp_path / "souls"
    empty.mkdir()
    with pytest.raises(SoulMissingError):
        get_soul("aetheria", souls_dir=empty)


def test_get_soul_missing_returns_empty_when_explicitly_configured(tmp_path):
    empty = tmp_path / "souls"
    empty.mkdir()
    text = get_soul("aetheria", souls_dir=empty, raise_on_missing=False)
    assert text == ""


def test_get_soul_rejects_retired_agent(souls_dir):
    # Even if a retired-named file is on disk, the loader refuses to serve it.
    (souls_dir / "scout.md").write_text("legacy scout content\n", encoding="utf-8")
    with pytest.raises(SoulNameError):
        get_soul("scout", souls_dir=souls_dir)


def test_get_soul_rejects_unknown_agent(souls_dir):
    with pytest.raises(SoulNameError):
        get_soul("not_an_agent", souls_dir=souls_dir)


def test_get_soul_rejects_path_traversal(souls_dir):
    """Defense in depth — agent name with / or .. must not escape souls_dir."""
    with pytest.raises(SoulNameError):
        get_soul("../etc/passwd", souls_dir=souls_dir)
    with pytest.raises(SoulNameError):
        get_soul("aetheria/../../etc/passwd", souls_dir=souls_dir)


def test_get_soul_defaults_to_env_souls_dir(monkeypatch, tmp_path):
    """Calling without explicit souls_dir falls back to EnvConfig's souls_dir."""
    fake_dir = tmp_path / "from_env"
    fake_dir.mkdir()
    (fake_dir / "aetheria.md").write_text("from env\n", encoding="utf-8")
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_dir))
    text = get_soul("aetheria")
    assert text.strip() == "from env"
