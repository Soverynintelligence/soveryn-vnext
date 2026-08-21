"""PDF text-layer extract (cite-or-stop).

Uses pypdf. Scanned / empty / encrypted PDFs return ``status=failed|partial``
with an explicit gap message — never fabricated page text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Soft cap so a 400-page dump cannot blow the context window in one splice.
DEFAULT_MAX_CHARS = 48_000


@dataclass(frozen=True)
class ExtractResult:
    """Outcome of a PDF extract attempt."""

    status: str  # ok | partial | failed
    text: str
    page_count: int
    pages_with_text: int
    chars: int
    truncated: bool = False
    gap: str | None = None
    source_name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def preamble(self) -> str:
        """Short honesty header for splicing into a chat turn."""
        name = self.source_name or "document.pdf"
        head = (
            f"[Intake: {name} — {self.page_count} page(s), "
            f"{self.pages_with_text} with text, status={self.status}"
        )
        if self.truncated:
            head += ", truncated"
        head += "]"
        if self.gap:
            head += f"\nGap: {self.gap}"
        return head


def extract_pdf_bytes(
    data: bytes,
    *,
    source_name: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ExtractResult:
    """Extract text from PDF bytes. Never invents content."""
    if not data:
        return ExtractResult(
            status="failed",
            text="",
            page_count=0,
            pages_with_text=0,
            chars=0,
            gap="empty file",
            source_name=source_name,
        )
    if not data.startswith(b"%PDF"):
        return ExtractResult(
            status="failed",
            text="",
            page_count=0,
            pages_with_text=0,
            chars=0,
            gap="not a PDF (missing %PDF header)",
            source_name=source_name,
        )

    try:
        from pypdf import PdfReader
        from io import BytesIO

        reader = PdfReader(BytesIO(data), strict=False)
    except Exception as exc:  # noqa: BLE001 — extract must stay best-effort
        return ExtractResult(
            status="failed",
            text="",
            page_count=0,
            pages_with_text=0,
            chars=0,
            gap=f"could not open PDF: {type(exc).__name__}: {exc}",
            source_name=source_name,
        )

    if getattr(reader, "is_encrypted", False):
        try:
            # Empty password sometimes works for "open" encryption.
            reader.decrypt("")
        except Exception:
            return ExtractResult(
                status="failed",
                text="",
                page_count=len(reader.pages) if reader.pages is not None else 0,
                pages_with_text=0,
                chars=0,
                gap="PDF is encrypted; cannot extract without a password",
                source_name=source_name,
            )

    parts: list[str] = []
    pages_with_text = 0
    page_count = len(reader.pages)
    for i, page in enumerate(reader.pages):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            parts.append(f"\n--- page {i + 1} ---\n[extract error: {type(exc).__name__}]")
            continue
        text = raw.strip()
        if text:
            pages_with_text += 1
            parts.append(f"\n--- page {i + 1} ---\n{text}")
        else:
            parts.append(f"\n--- page {i + 1} ---\n[no text layer on this page]")

    joined = "".join(parts).strip()
    truncated = False
    if len(joined) > max_chars:
        joined = joined[:max_chars].rstrip() + "\n\n[… truncated for context budget …]"
        truncated = True

    if page_count == 0:
        return ExtractResult(
            status="failed",
            text="",
            page_count=0,
            pages_with_text=0,
            chars=0,
            gap="PDF has no pages",
            source_name=source_name,
        )

    if pages_with_text == 0:
        return ExtractResult(
            status="failed",
            text=joined,
            page_count=page_count,
            pages_with_text=0,
            chars=len(joined),
            truncated=truncated,
            gap=(
                "no extractable text layer — likely a scan or image-only PDF. "
                "OCR is not in v0 intake; print the gap, do not invent page content."
            ),
            source_name=source_name,
        )

    status = "ok" if pages_with_text == page_count and not truncated else "partial"
    gap = None
    if pages_with_text < page_count:
        gap = (
            f"{page_count - pages_with_text} page(s) had no text layer "
            "(scan/image or empty)"
        )
    if truncated:
        gap = (gap + "; " if gap else "") + f"text truncated to {max_chars} characters"

    return ExtractResult(
        status=status,
        text=joined,
        page_count=page_count,
        pages_with_text=pages_with_text,
        chars=len(joined),
        truncated=truncated,
        gap=gap,
        source_name=source_name,
    )


def extract_pdf_path(
    path: str | Path,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> ExtractResult:
    """Extract text from a PDF on disk."""
    p = Path(path)
    if not p.is_file():
        return ExtractResult(
            status="failed",
            text="",
            page_count=0,
            pages_with_text=0,
            chars=0,
            gap=f"file not found: {p}",
            source_name=p.name,
        )
    try:
        data = p.read_bytes()
    except OSError as exc:
        return ExtractResult(
            status="failed",
            text="",
            page_count=0,
            pages_with_text=0,
            chars=0,
            gap=f"could not read file: {exc}",
            source_name=p.name,
        )
    return extract_pdf_bytes(data, source_name=p.name, max_chars=max_chars)


def splice_into_message(user_message: str, results: list[ExtractResult]) -> str:
    """Prepend intake blocks to the user message for the model turn."""
    if not results:
        return user_message
    blocks: list[str] = []
    for r in results:
        block = r.preamble()
        if r.text.strip():
            block += "\n\n" + r.text.strip()
        blocks.append(block)
    body = (user_message or "").strip()
    joined = "\n\n---\n\n".join(blocks)
    if body:
        return f"{joined}\n\n---\n\n{body}"
    return joined
