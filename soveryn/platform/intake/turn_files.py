"""Turn-scoped in-flight file attachments (PDFs) for desk tools.

Chat PDFs are extracted for text and were never written to disk, so
file_away(path=\"attachment-1.pdf\") cannot work. Same ContextVar pattern
as turn_images: bind around the tool invoke, tools read path=\"current\".
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class InFlightFile:
    name: str
    data: bytes
    mime: str = "application/pdf"


in_flight_files: ContextVar[tuple[InFlightFile, ...]] = ContextVar(
    "intake_in_flight_files", default=(),
)


def bind_turn_files(files: tuple[InFlightFile, ...] | None) -> Token:
    return in_flight_files.set(tuple(files) if files else ())


def reset_turn_files(token: Token) -> None:
    in_flight_files.reset(token)


def current_turn_files() -> tuple[InFlightFile, ...]:
    return in_flight_files.get()


@contextmanager
def turn_files_bound(files: tuple[InFlightFile, ...] | None) -> Iterator[None]:
    token = bind_turn_files(files)
    try:
        yield
    finally:
        reset_turn_files(token)


def parse_current_index(src: str) -> int | None:
    """'current' -> 0, 'current:2' -> 1. None if this is a real path."""
    s = (src or "").strip().lower()
    if s == "current":
        return 0
    if s.startswith("current:"):
        rest = s.split(":", 1)[1].strip()
        if rest.isdigit() and int(rest) >= 1:
            return int(rest) - 1
        return None
    return None


def files_from_pdf_data_urls(urls: tuple[str, ...]) -> tuple[InFlightFile, ...]:
    """Decode data:application/pdf URLs into in-flight files."""
    import base64

    out: list[InFlightFile] = []
    for i, url in enumerate(urls):
        if not isinstance(url, str) or not url.startswith("data:application/pdf"):
            continue
        if "," not in url:
            continue
        b64 = url.split(",", 1)[-1]
        try:
            data = base64.b64decode(b64, validate=False)
        except Exception:
            continue
        out.append(
            InFlightFile(
                name=f"attachment-{i + 1}.pdf",
                data=data,
                mime="application/pdf",
            )
        )
    return tuple(out)


def pick_current(src: str) -> InFlightFile | None:
    idx = parse_current_index(src)
    if idx is None:
        return None
    files = current_turn_files()
    if 0 <= idx < len(files):
        return files[idx]
    return None
