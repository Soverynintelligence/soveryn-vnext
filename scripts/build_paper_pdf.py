#!/usr/bin/env python
"""Render a SOVERYN paper from Markdown to a print-ready PDF.

    python scripts/build_paper_pdf.py docs/papers/a-false-confession.md out.pdf

Deliberately plain typography. These papers are read by people deciding whether
to trust a measurement, so the page should get out of the way — a serif body at
a comfortable measure, real tables, and no brand furniture competing with the
numbers. The only colour is a single copper rule under the title.

markdown + weasyprint only; both are already in the soveryn env. No pandoc, no
LaTeX, nothing new to install.
"""
from __future__ import annotations

import sys
from pathlib import Path

import markdown
from weasyprint import HTML

CSS = """
@page {
  size: A4;
  margin: 22mm 20mm 20mm 20mm;
  @bottom-center {
    content: counter(page);
    font-family: Georgia, serif; font-size: 9pt; color: #7a7a7a;
  }
}
body {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 10.5pt; line-height: 1.55; color: #1a1a1a;
  hyphens: auto;
}
h1 {
  font-size: 22pt; line-height: 1.15; margin: 0 0 2mm 0;
  letter-spacing: -0.01em; font-weight: normal;
  border-bottom: 2px solid #9a5b2d;   /* aged copper */
  padding-bottom: 3mm;
}
h3 { font-size: 12pt; font-weight: normal; font-style: italic;
     color: #444; margin: 3mm 0 5mm 0; line-height: 1.35; }
h2 { font-size: 13pt; margin: 8mm 0 2.5mm 0; font-weight: bold;
     page-break-after: avoid; }
p { margin: 0 0 3mm 0; text-align: justify; }
strong { font-weight: bold; }
em { font-style: italic; }
code, pre {
  font-family: "DejaVu Sans Mono", monospace; font-size: 8.8pt;
  background: #f4f2ee;
}
code { padding: 0.5mm 1mm; }
pre { padding: 3mm; border-left: 2px solid #7d8c6f; overflow-wrap: break-word;
      white-space: pre-wrap; }
table {
  border-collapse: collapse; width: 100%; font-size: 8.8pt;
  margin: 4mm 0 5mm 0; page-break-inside: avoid;
}
th, td { border-bottom: 0.5pt solid #ccc; padding: 2mm 2.5mm;
         text-align: left; vertical-align: top; }
th { border-bottom: 1pt solid #666; font-weight: bold; }
blockquote {
  margin: 4mm 0; padding: 0 0 0 5mm; border-left: 2px solid #9a5b2d;
  font-style: italic; color: #333;
}
hr { border: none; border-top: 0.5pt solid #ddd; margin: 6mm 0; }
a { color: #1a1a1a; text-decoration: none; border-bottom: 0.5pt solid #9a5b2d; }
ol, ul { margin: 0 0 3mm 0; padding-left: 6mm; }
li { margin-bottom: 1.5mm; }
h2 + p, h3 + p { margin-top: 0; }
"""


def build(src: Path, out: Path) -> None:
    html_body = markdown.markdown(
        src.read_text(encoding="utf-8"),
        extensions=["tables", "attr_list", "sane_lists"],
    )
    doc = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html_body}</body></html>"
    HTML(string=doc, base_url=str(src.parent)).write_pdf(str(out))
    print(f"  {out}  ({out.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(1)
    build(Path(sys.argv[1]), Path(sys.argv[2]))
