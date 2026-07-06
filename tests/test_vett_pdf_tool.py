"""Vett's convert_to_pdf tool — deterministic file -> PDF.

Vett choked (2026-07-06) trying to "make a PDF" by regenerating an 8KB doc
into a tool-call argument, which truncated ("missing closing quote" 500). A
PDF is binary a model can't emit; conversion belongs in a tool. This gives
her one: file path in, PDF path out, no model in the loop.
"""
from pathlib import Path

from soveryn.agents.vett.tools.pdf import build_convert_to_pdf_tool


def test_tool_identity():
    tool = build_convert_to_pdf_tool()
    assert tool.name == "convert_to_pdf"
    assert tool.owner == "vett"
    assert tool.schema["required"] == ["source_path"]


def test_converts_markdown_to_valid_pdf(tmp_path):
    src = tmp_path / "doc.md"
    src.write_text("# Title\n\nHello **world** — a test.\n\n- one\n- two\n")
    res = build_convert_to_pdf_tool().handler({"source_path": str(src)})
    assert res.get("ok") is True
    out = Path(res["output_path"])
    assert out.exists() and out.suffix == ".pdf"
    assert out.read_bytes()[:5] == b"%PDF-"   # a real PDF
    assert res["bytes"] > 500


def test_custom_output_path_and_parent_created(tmp_path):
    src = tmp_path / "d.md"
    src.write_text("# Hi\n")
    dst = tmp_path / "nested" / "out" / "custom.pdf"   # parent does not exist yet
    res = build_convert_to_pdf_tool().handler(
        {"source_path": str(src), "output_path": str(dst)})
    assert res.get("ok") is True
    assert Path(res["output_path"]) == dst and dst.exists()


def test_missing_file_errors(tmp_path):
    res = build_convert_to_pdf_tool().handler({"source_path": str(tmp_path / "nope.md")})
    assert res.get("error") == "not_found"


def test_missing_source_arg_errors():
    res = build_convert_to_pdf_tool().handler({})
    assert res.get("error") == "bad_args"


def test_oversized_file_refused(tmp_path):
    src = tmp_path / "big.md"
    src.write_text("x" * 2000)
    res = build_convert_to_pdf_tool(max_bytes=1000).handler({"source_path": str(src)})
    assert res.get("error") == "too_large"
