"""Map assistant chat text to /aetheria/img/ URLs for Messages.

Comfy stills are not stored as attachments — Eve names files or says #8.
Messages has to turn that into the same route the desk already serves.
"""
from __future__ import annotations

import re
from pathlib import Path

_SAFE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,127}\.(?:png|jpg|jpeg|webp|gif)$"
)
_NAME = re.compile(
    r"\b((?:eve|aetheria)_[A-Za-z0-9_\-]{1,120}\.(?:png|jpg|jpeg|webp|gif))\b",
    re.I,
)
_URL = re.compile(
    r"/aetheria/img/([A-Za-z0-9][A-Za-z0-9_\-]{0,127}\.(?:png|jpg|jpeg|webp|gif))"
)
_PATH = re.compile(
    r"(?:~/)?ComfyUI/output/([A-Za-z0-9][A-Za-z0-9_\-]{0,127}\.(?:png|jpg|jpeg|webp|gif))"
)
_HASH = re.compile(r"(?:^|[\s(])#(\d{1,2})\b")
# Do not treat "Spark #1" / "Entry #1" as stills — only hash-refs on turns
# that are actually talking about generated pictures.
_STILL_TURN = re.compile(
    r"(?i)("
    r"eve_\d{3,}|aetheria_\d{3,}|\.png\b|comfyui|generate_image|"
    r"\bstills\b|honest eyes|"
    r"generated (?:those|them|the (?:pic|face|still))"
    r")"
)

OUTPUT_DIR = Path.home() / "ComfyUI" / "output"


def _chat_url(name: str) -> str | None:
    base = str(name or "").split("/")[-1]
    if not _SAFE.match(base):
        return None
    return f"/aetheria/img/{base}"


def comfy_urls_from_text(
    text: str,
    *,
    output_dir: Path | None = None,
) -> list[str]:
    """Return UI URLs for Comfy stills mentioned in a turn."""
    seen: set[str] = set()
    out: list[str] = []

    def add(name: str) -> None:
        url = _chat_url(name)
        if not url or url in seen:
            return
        seen.add(url)
        out.append(url)

    blob = text or ""
    for rx in (_URL, _PATH, _NAME):
        for match in rx.finditer(blob):
            add(match.group(1))

    root = output_dir if output_dir is not None else OUTPUT_DIR
    if _STILL_TURN.search(blob):
        for match in _HASH.finditer(blob):
            n = int(match.group(1))
            if n < 1:
                continue
            for prefix in ("eve", "aetheria"):
                filename = f"{prefix}_{n:05d}_.png"
                if (root / filename).is_file():
                    add(filename)
                    break
    return out
