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

from soveryn.agents.scotty.tools.paths import (
    PathOutOfBoundsError,
    resolve_within_root,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec

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


# --- PDF READER -------------------------------------------------------------

_READ_PDF_MAX_BYTES = 30 * 1024 * 1024   # dealer packets run ~17 MB
_READ_PDF_MAX_CHARS = 40 * 1024          # ~10K tokens — page through bigger docs
_READ_PDF_MAX_PAGES = 40                 # per call; use `pages` for the rest


def _parse_page_range(pages_arg: Any, total: int) -> list[int]:
    """Turn a 1-based 'pages' arg ('3', '1-5') into 0-based page indices.
    Falls back to every page (the loop's char/page caps still bound it)."""
    if not isinstance(pages_arg, str) or not pages_arg.strip():
        return list(range(total))
    s = pages_arg.strip()
    try:
        if "-" in s:
            a, b = s.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(s)
    except ValueError:
        return list(range(total))
    start = max(1, start)
    end = min(total, max(start, end))
    return list(range(start - 1, end))


def build_read_pdf_tool(
    *, owner_agent: str = "vett", root: Path | None = None
) -> ToolSpec:
    """Bounded PDF text + form-field reader (PyMuPDF/fitz).

    A PDF is binary, so the plain read_file tool returns garbage on one. This
    extracts the real page text AND any fillable form-field values (AcroForm),
    which is what "read the form" actually needs. `root` fences every read
    (defaults to home, matching Vett's read_file surface); symlink escapes are
    rejected by resolve_within_root.
    """
    read_root = root or Path.home()

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path", "")
        if not isinstance(path_arg, str) or not path_arg:
            raise ToolArgError("path (string) is required")
        try:
            resolved = resolve_within_root(path_arg, root=read_root, must_exist=True)
        except PathOutOfBoundsError as e:
            raise ToolArgError(str(e))
        except FileNotFoundError as e:
            raise ToolArgError(str(e))
        if not resolved.is_file():
            raise ToolArgError(f"path {path_arg!r} is not a regular file")

        size = resolved.stat().st_size
        if size > _READ_PDF_MAX_BYTES:
            return {"error": "too_large",
                    "message": f"{resolved.name} is {size} bytes; cap is {_READ_PDF_MAX_BYTES}."}

        try:
            import fitz  # PyMuPDF
        except Exception as e:  # noqa: BLE001 — report, don't crash the agent
            return {"error": "pdf_lib_missing", "message": f"PyMuPDF unavailable: {e}"}

        try:
            doc = fitz.open(str(resolved))
        except Exception as e:  # noqa: BLE001
            return {"error": "open_failed", "message": str(e)}

        try:
            if getattr(doc, "needs_pass", False):
                return {"error": "encrypted",
                        "message": f"{resolved.name} is password-protected."}
            total = doc.page_count
            texts: list[str] = []
            fields: dict[str, str] = {}
            chars = 0
            pages_read = 0
            truncated = False
            for i in _parse_page_range(args.get("pages"), total):
                if pages_read >= _READ_PDF_MAX_PAGES or chars >= _READ_PDF_MAX_CHARS:
                    truncated = True
                    break
                page = doc[i]
                t = page.get_text() or ""
                if chars + len(t) > _READ_PDF_MAX_CHARS:
                    t = t[: max(0, _READ_PDF_MAX_CHARS - chars)]
                    truncated = True
                texts.append(t)
                chars += len(t)
                pages_read += 1
                try:  # AcroForm widgets — the "form" part
                    for w in (page.widgets() or []):
                        name = getattr(w, "field_name", None)
                        if name:
                            val = getattr(w, "field_value", None)
                            fields[name] = "" if val is None else str(val)
                except Exception:  # noqa: BLE001 — a page without widgets is normal
                    pass

            text = "\n\n".join(texts).strip()
            result: dict[str, Any] = {
                "path": str(resolved),
                "page_count": total,
                "pages_read": pages_read,
                "text": text,
                "truncated": truncated,
            }
            if fields:
                result["form_fields"] = fields
            if not text and not fields:
                result["note"] = (
                    "No extractable text — this PDF is likely scanned/image-only. "
                    "OCR is not supported by this tool."
                )
            return result
        finally:
            doc.close()

    return ToolSpec(
        name="read_pdf",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to the PDF. Fenced to the home dir; "
                        "symlink escapes are rejected."
                    ),
                },
                "pages": {
                    "type": "string",
                    "description": (
                        "Optional 1-based page range, e.g. '1-5' or '3'. Default "
                        "reads from page 1 up to the page/character cap — use a "
                        "range to page through large documents."
                    ),
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Read a PDF's actual text AND any fillable form-field values "
            "(AcroForm). Use this for PDFs — the plain read_file tool returns "
            f"binary garbage on them. Returns page text (up to ~{_READ_PDF_MAX_CHARS // 1024} KB / "
            f"{_READ_PDF_MAX_PAGES} pages per call; use 'pages' to read the rest) "
            "plus form_fields when the PDF is a fillable form. Scanned/image-only "
            "PDFs return a note (no OCR)."
        ),
    )


# --- PDF -> EDITABLE DOCX ----------------------------------------------------

_TO_DOCX_MAX_BYTES = 30 * 1024 * 1024   # match read_pdf's cap
_TO_DOCX_MAX_PAGES = 50                  # bound conversion work


def build_pdf_to_editable_doc_tool(
    *,
    owner_agent: str = "vett",
    root: Path | None = None,
    writable_root: Path | None = None,
) -> ToolSpec:
    """Convert a text-layer PDF into an editable .docx (pdf2docx).

    Reads are fenced to `root` (defaults to home, matching read_pdf); the .docx
    is written ONLY inside `writable_root` (defaults to ~/Downloads) so this tool
    cannot write outside Vett's drop dir — the output name is reduced to a bare
    filename, never a path. Scanned/image-only PDFs have no text layer, so
    pdf2docx would just embed a picture; those are rejected with a clear
    "needs OCR" message instead of producing a fake-editable doc.
    """
    read_root = root or Path.home()
    write_root = writable_root or (Path.home() / "Downloads")

    def handler(args: Mapping[str, Any]) -> Any:
        path_arg = args.get("path", "")
        if not isinstance(path_arg, str) or not path_arg:
            raise ToolArgError("path (string) is required")
        try:
            resolved = resolve_within_root(path_arg, root=read_root, must_exist=True)
        except PathOutOfBoundsError as e:
            raise ToolArgError(str(e))
        except FileNotFoundError as e:
            raise ToolArgError(str(e))
        if not resolved.is_file():
            raise ToolArgError(f"path {path_arg!r} is not a regular file")
        if resolved.suffix.lower() != ".pdf":
            return {"error": "not_pdf", "message": f"{resolved.name} is not a .pdf."}

        size = resolved.stat().st_size
        if size > _TO_DOCX_MAX_BYTES:
            return {"error": "too_large",
                    "message": f"{resolved.name} is {size} bytes; cap is {_TO_DOCX_MAX_BYTES}."}

        # Output is a bare filename dropped into the writable root — never a path,
        # so this tool can't be steered into writing outside ~/Downloads.
        out_arg = args.get("output_name")
        if isinstance(out_arg, str) and out_arg.strip():
            name = Path(out_arg.strip()).name
            if not name.lower().endswith(".docx"):
                name += ".docx"
        else:
            name = resolved.stem + ".editable.docx"

        try:
            import fitz  # PyMuPDF — cheap text-layer probe before the heavy convert
        except Exception as e:  # noqa: BLE001
            return {"error": "pdf_lib_missing", "message": f"PyMuPDF unavailable: {e}"}
        try:
            doc = fitz.open(str(resolved))
        except Exception as e:  # noqa: BLE001
            return {"error": "open_failed", "message": str(e)}
        try:
            if getattr(doc, "needs_pass", False):
                return {"error": "encrypted",
                        "message": f"{resolved.name} is password-protected."}
            total_pages = doc.page_count
            end_page = min(total_pages, _TO_DOCX_MAX_PAGES)
            text_chars = sum(len(doc[i].get_text() or "") for i in range(end_page))
        finally:
            doc.close()

        if text_chars < 10:
            return {
                "error": "scanned_no_text",
                "message": (
                    f"{resolved.name} has no text layer (image-only scan). "
                    "pdf2docx would only embed a picture, not editable text. "
                    "This needs OCR, which this tool does not do."
                ),
            }

        try:
            from pdf2docx import Converter
        except Exception as e:  # noqa: BLE001
            return {"error": "pdf2docx_missing", "message": f"pdf2docx unavailable: {e}"}

        write_root.mkdir(parents=True, exist_ok=True)
        out_path = write_root / name
        try:
            cv = Converter(str(resolved))
            try:
                cv.convert(str(out_path), start=0, end=end_page)
            finally:
                cv.close()
        except Exception as e:  # noqa: BLE001 — report, don't crash the agent
            return {"error": "convert_failed", "message": str(e)}

        result: dict[str, Any] = {
            "ok": True,
            "output_path": str(out_path),
            "bytes": out_path.stat().st_size if out_path.exists() else 0,
            "pages_converted": end_page,
        }
        if total_pages > _TO_DOCX_MAX_PAGES:
            result["note"] = (
                f"Only the first {_TO_DOCX_MAX_PAGES} of {total_pages} pages were "
                "converted (page cap)."
            )
        return result

    return ToolSpec(
        name="pdf_to_editable_doc",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute path to the source PDF. Fenced to the home dir; "
                        "symlink escapes are rejected. Must have a real text layer "
                        "(a digital PDF, not a scan)."
                    ),
                },
                "output_name": {
                    "type": "string",
                    "description": (
                        "Optional output filename (not a path). The .docx is always "
                        "written into ~/Downloads. Defaults to "
                        "'<source>.editable.docx'."
                    ),
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Convert a text-layer PDF into an EDITABLE Word (.docx) that mirrors "
            "the layout, written into ~/Downloads. Use this for 'make this PDF "
            "editable'. Works ONLY on digital PDFs with a real text layer — a "
            "scanned/image-only PDF is rejected (it would just embed a picture; "
            "that needs OCR, which this does not do). If unsure whether a PDF has "
            "text, check with read_pdf first."
        ),
    )


def register_vett_pdf_tools(
    registry, *, owner_agent: str = "vett", read_root: Path | None = None
) -> None:
    """Register Vett's PDF tools (convert-to-pdf writer + read_pdf reader +
    pdf_to_editable_doc converter)."""
    registry.register(build_convert_to_pdf_tool(owner_agent=owner_agent))
    registry.register(build_read_pdf_tool(owner_agent=owner_agent, root=read_root))
    registry.register(
        build_pdf_to_editable_doc_tool(owner_agent=owner_agent, root=read_root)
    )
