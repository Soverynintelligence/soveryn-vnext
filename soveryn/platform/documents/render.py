"""
soveryn.platform.documents.render
===================================
Render pipeline: markdown -> HTML -> PDF / DOCX

Tools used:
  - `markdown` lib (in-process)           — md -> HTML fragment
  - `weasyprint` (in-process)             — HTML -> PDF bytes
  - `libreoffice --headless` (subprocess) — HTML -> DOCX bytes

PDF via weasyprint is the fast, no-subprocess path.
DOCX via libreoffice is slower; isolated with a throwaway user profile so
concurrent calls don't collide and the system LO profile stays untouched.
"""

from __future__ import annotations

import subprocess
import tempfile
import os
from pathlib import Path

import markdown as _md_lib


# ---------------------------------------------------------------------------
# Minimal professional print CSS
# ---------------------------------------------------------------------------

_PRINT_CSS = """
* {
  box-sizing: border-box;
}
body {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 11pt;
  line-height: 1.6;
  color: #111;
  max-width: 720px;
  margin: 0 auto;
  padding: 1.5em 2em;
}
h1, h2, h3, h4, h5, h6 {
  font-family: 'Helvetica Neue', Arial, sans-serif;
  font-weight: 700;
  margin-top: 1.4em;
  margin-bottom: 0.4em;
  color: #000;
}
h1 { font-size: 20pt; border-bottom: 2px solid #ccc; padding-bottom: 0.2em; }
h2 { font-size: 15pt; border-bottom: 1px solid #ddd; padding-bottom: 0.15em; }
h3 { font-size: 13pt; }
p  { margin: 0.6em 0; }
ul, ol { margin: 0.5em 0 0.5em 1.5em; padding: 0; }
li { margin: 0.25em 0; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
  font-size: 10pt;
}
th, td {
  border: 1px solid #aaa;
  padding: 0.4em 0.6em;
  text-align: left;
}
th { background: #f0f0f0; font-weight: bold; }
code {
  font-family: 'Courier New', Courier, monospace;
  font-size: 9.5pt;
  background: #f5f5f5;
  padding: 0.1em 0.3em;
  border-radius: 2px;
}
pre code {
  display: block;
  padding: 0.8em 1em;
  white-space: pre-wrap;
  word-break: break-all;
}
blockquote {
  border-left: 3px solid #aaa;
  margin: 0.8em 0;
  padding: 0.2em 1em;
  color: #555;
}
a { color: #1a5fa8; }
@media print {
  body { padding: 0; }
  a    { color: #000; text-decoration: none; }
}
"""


# ---------------------------------------------------------------------------
# md_to_html
# ---------------------------------------------------------------------------

def md_to_html(markdown_text: str, *, title: str = "") -> str:
    """Convert a markdown string into a full standalone HTML document.

    Uses the ``markdown`` library with 'extra', 'tables', and 'sane_lists'
    extensions.  The returned string is a complete ``<html>…</html>`` doc
    with an embedded print-ready CSS stylesheet.
    """
    extensions = ["extra", "tables", "sane_lists"]
    body_html = _md_lib.markdown(markdown_text, extensions=extensions)

    escaped_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{escaped_title}</title>
<style>
{_PRINT_CSS}
</style>
</head>
<body>
{body_html}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# html_to_pdf
# ---------------------------------------------------------------------------

def html_to_pdf(html: str) -> bytes:
    """Render an HTML string to PDF bytes using WeasyPrint."""
    from weasyprint import HTML  # local import — slow first load
    return HTML(string=html).write_pdf()


# ---------------------------------------------------------------------------
# html_to_docx
# ---------------------------------------------------------------------------

def html_to_docx(html: str) -> bytes:
    """Convert an HTML string to DOCX bytes via LibreOffice headless.

    LibreOffice cannot convert HTML → DOCX directly (no export filter).
    The conversion is done in two steps: HTML → ODT (writer/web filter),
    then ODT → DOCX (MS Word 2007 XML filter).

    A throwaway temporary directory is used for all intermediate files
    and as LibreOffice's user-profile location so concurrent calls don't
    collide and the system LO profile stays untouched.

    Raises
    ------
    RuntimeError
        If either libreoffice call exits non-zero, times out, or the
        expected output file is absent or empty.
    """
    with tempfile.TemporaryDirectory(prefix="soveryn_lo_") as tmpdir:
        html_path = Path(tmpdir) / "input.html"
        html_path.write_text(html, encoding="utf-8")

        lo_profile = Path(tmpdir) / "lo_profile"
        lo_profile.mkdir()

        def _run_lo(convert_to: str, source: Path) -> None:
            cmd = [
                "libreoffice",
                f"-env:UserInstallation=file://{lo_profile}",
                "--headless",
                "--convert-to", convert_to,
                "--outdir", tmpdir,
                str(source),
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=60,
                    text=True,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"libreoffice --convert-to {convert_to} timed out after 60s"
                ) from exc

            if result.returncode != 0:
                raise RuntimeError(
                    f"libreoffice --convert-to {convert_to} failed "
                    f"(exit {result.returncode}):\n{result.stderr.strip()}"
                )

        # Step 1: HTML → ODT
        _run_lo("odt", html_path)
        odt_path = Path(tmpdir) / "input.odt"
        if not odt_path.exists():
            raise RuntimeError(
                f"libreoffice HTML→ODT produced no output at {odt_path}"
            )

        # Step 2: ODT → DOCX
        _run_lo("docx", odt_path)
        docx_path = Path(tmpdir) / "input.docx"
        if not docx_path.exists():
            raise RuntimeError(
                f"libreoffice ODT→DOCX produced no output at {docx_path}"
            )

        data = docx_path.read_bytes()
        if not data:
            raise RuntimeError("libreoffice produced an empty .docx file")

        return data


# ---------------------------------------------------------------------------
# render_document — dispatcher
# ---------------------------------------------------------------------------

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_FMT_MIME: dict[str, str] = {
    "md":   "text/markdown",
    "html": "text/html",
    "pdf":  "application/pdf",
    "docx": _DOCX_MIME,
}


def render_document(
    content: str,
    fmt: str,
    *,
    title: str = "",
) -> tuple[bytes, str]:
    """Render *content* (markdown text) to the requested format.

    Parameters
    ----------
    content:
        Source markdown string.
    fmt:
        One of ``'md'``, ``'html'``, ``'pdf'``, ``'docx'``.
    title:
        Optional document title (used for HTML <title> and as a hint for
        converters that support it).

    Returns
    -------
    (bytes, mime_type)

    Raises
    ------
    ValueError
        If *fmt* is not one of the recognised format strings.
    """
    fmt = fmt.lower().strip()
    if fmt not in _FMT_MIME:
        raise ValueError(
            f"Unknown render format {fmt!r}. "
            f"Supported: {sorted(_FMT_MIME)}"
        )

    mime = _FMT_MIME[fmt]

    if fmt == "md":
        return content.encode(), mime

    html = md_to_html(content, title=title)

    if fmt == "html":
        return html.encode(), mime

    if fmt == "pdf":
        return html_to_pdf(html), mime

    # fmt == "docx"
    return html_to_docx(html), mime
