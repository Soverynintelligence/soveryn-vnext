"""Tests for Aetheria read_soul_origin tool (Memory Grades PR5)."""

from soveryn.agents.aetheria.tools.soul_origin import build_read_soul_origin_tool


def test_read_soul_origin_returns_content(tmp_path):
    souls = tmp_path / "souls"
    souls.mkdir()
    (souls / "aetheria.origin.md").write_text(
        "# HOW WE BECAME SOVERYN\n\nLattice story.\n", encoding="utf-8",
    )
    tool = build_read_soul_origin_tool(souls_dir=souls, owner_agent="aetheria")
    assert tool.name == "read_soul_origin"
    assert tool.owner == "aetheria"
    out = tool.handler({})
    assert out["ok"] is True
    assert "Lattice story" in out["content"]


def test_read_soul_origin_missing(tmp_path):
    souls = tmp_path / "souls"
    souls.mkdir()
    tool = build_read_soul_origin_tool(souls_dir=souls, owner_agent="aetheria")
    out = tool.handler({})
    assert out["ok"] is False
    assert out["error"] == "soul_origin_missing"
