"""Vett's file -> PDF conversion tool.

Deterministic file-in / file-out. Vett calls this instead of trying to
regenerate a document's content into a tool-call argument — a PDF is a binary
format a language model cannot emit, and echoing a long doc into a JSON string
truncates ("missing closing quote" 500, 2026-07-06). Format conversion is a
mechanical job; it belongs in a tool, not in the model's output.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from soveryn.platform.tools.registry import ToolSpec

_DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # bounded surface — don't convert huge files

_HTML_EXTS = {".html", ".htm"}

_CSS = """
@page { size: Letter; margin: 0.9in; @bottom-center { content: counter(page); color:#999; font-size:9pt; } }
body { font-family:'DejaVu Sans','Noto Sans',Arial,sans-serif; font-size:10.5pt; line-height:1.5; color:#1b1b1b; }
h1 { font-size:21pt; color:#14213d; border-bottom:3px solid #14213d; padding-bottom:5px; }
h2 { font-size:14pt; color:#14213d; margin-top:1.3em; border-bottom:1px solid #d0d0d0; padding-bottom:3px; }
h3 { font-size:11.5pt; color:#26417a; margin-top:1em; }
strong { color:#000; } em { color:#333; }
code { background:#f2f2f4; padding:1px 4px; border-radius:3px; font-family:'DejaVu Sans Mono',monospace; font-size:9pt; }
blockquote { border-left:4px solid #c9a227; background:#fbf7e9; margin:1em 0; padding:.5em 1em; }
hr { border:none; border-top:1px solid #ddd; margin:1.5em 0; }
ul,ol { margin:.3em 0 .7em 1.1em; } li { margin:.2em 0; }
"""


def build_convert_to_pdf_tool(
    *, owner_agent: str = "vett", max_bytes: int = _DEFAULT_MAX_BYTES
) -> ToolSpec:
    """A deterministic Markdown/HTML -> PDF converter tool for Vett."""

    def handler(args: Mapping[str, Any]) -> Any:
        source = args.get("source_path")
        if not source or not isinstance(source, str):
            return {"error": "bad_args", "message": "source_path (string) is required."}
        src = Path(source).expanduser()
        if not src.is_file():
            return {"error": "not_found", "message": f"No file at {src}."}
        size = src.stat().st_size
        if size > max_bytes:
            return {"error": "too_large",
                    "message": f"{src.name} is {size} bytes; cap is {max_bytes}."}

        out = args.get("output_path")
        out_path = (Path(out).expanduser()
                    if isinstance(out, str) and out.strip()
                    else src.with_suffix(".pdf"))
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"error": "read_failed", "message": str(e)}

        try:
            import weasyprint
            if src.suffix.lower() in _HTML_EXTS:
                html = text
            else:
                import markdown
                body = markdown.markdown(
                    text, extensions=["extra", "sane_lists", "smarty"])
                html = (f"<html><head><meta charset='utf-8'><style>{_CSS}</style>"
                        f"</head><body>{body}</body></html>")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            weasyprint.HTML(string=html, base_url=str(src.parent)).write_pdf(str(out_path))
        except Exception as e:  # weasyprint/markdown failure — report, don't crash
            return {"error": "convert_failed", "message": str(e)}

        return {"ok": True, "output_path": str(out_path), "bytes": out_path.stat().st_size}

    return ToolSpec(
        name="convert_to_pdf",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Absolute path to the Markdown or HTML file to convert.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional output PDF path. Defaults to the source path with a .pdf suffix.",
                },
            },
            "required": ["source_path"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Convert a Markdown or HTML file to a PDF. Deterministic file-in/"
            "file-out: give the source file's path and it writes a PDF and "
            "returns its path. It does NOT regenerate the document's content — "
            "use this for 'make a PDF of X' instead of emitting the text yourself."
        ),
    )


def register_vett_pdf_tools(registry, *, owner_agent: str = "vett") -> None:
    """Register Vett's convert_to_pdf tool onto the shared tool registry."""
    registry.register(build_convert_to_pdf_tool(owner_agent=owner_agent))
