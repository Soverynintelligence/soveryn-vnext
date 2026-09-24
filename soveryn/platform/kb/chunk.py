"""Boring markdown/PDF-text chunker for the reference KB. Jon can tighten later."""
from __future__ import annotations

from pathlib import Path

DEFAULT_MAX = 1200
DEFAULT_OVERLAP = 120
_DOC_SUFFIXES = {".md", ".txt", ".pdf"}


def chunk_markdown(
    text: str,
    *,
    source_path: str,
    max_chars: int = DEFAULT_MAX,
    overlap: int = DEFAULT_OVERLAP,
) -> list[tuple[str, str]]:
    """Return (chunk_id, body) pairs. Split on headings, then by length."""
    parts = _split_headings(text)
    out: list[tuple[str, str]] = []
    seq = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_chars:
            seq += 1
            out.append((f"{source_path}#{seq}", part))
            continue
        start = 0
        while start < len(part):
            end = min(len(part), start + max_chars)
            seq += 1
            out.append((f"{source_path}#{seq}", part[start:end].strip()))
            if end >= len(part):
                break
            start = max(end - overlap, start + 1)
    return out


def _split_headings(text: str) -> list[str]:
    chunks: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and buf:
            chunks.append("\n".join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        chunks.append("\n".join(buf))
    return chunks or [text]


def iter_doc_files(root: Path) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _DOC_SUFFIXES:
            continue
        if any(p in {".git", "node_modules", "__pycache__"} for p in path.parts):
            continue
        files.append(path)
    return files


def extract_pdf_text(path: Path) -> str:
    """Best-effort text layer. Empty if no extractor or a scan-only PDF."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
    except Exception:
        return ""
    pages: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            pages.append(text.strip())
    return "\n\n".join(pages)


def read_doc_text(path: Path) -> str:
    """Load markdown/txt as UTF-8, PDFs via the text layer."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    return path.read_text(encoding="utf-8", errors="replace")
