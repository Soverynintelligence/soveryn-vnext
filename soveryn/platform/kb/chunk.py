"""Boring markdown chunker for the reference KB. Jon can tighten later."""
from __future__ import annotations

from pathlib import Path

DEFAULT_MAX = 1200
DEFAULT_OVERLAP = 120


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
        if path.suffix.lower() not in {".md", ".txt"}:
            continue
        if any(p in {".git", "node_modules", "__pycache__"} for p in path.parts):
            continue
        files.append(path)
    return files
