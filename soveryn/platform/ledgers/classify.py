"""Route a receipt to SOVERYN, CWG, or unsorted. Never guess."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ClassifyHit:
    book: str  # soveryn | cwg | unsorted
    gap: str | None = None
    reasons: tuple[str, ...] = ()


_CWG_NAME = re.compile(r"cwg", re.I)
_SOVERYN_NAME = re.compile(r"soveryn|sovery", re.I)

_CWG_TEXT = (
    "aquascape",
    "hiblow",
    "dewenwils",
    "carolina water garden",
    "pond bacteria",
    "pond dosing",
    "koi pond",
    "pond liner",
    "waterfall",
    "aerator",
    "uv bulb",
    "uv light",
    "color-changing",
    "color changing",
    "pond and garden",
    "pond spotlight",
    "smart control hub",
    "carolinawatergardens",
)

_SOVERYN_TEXT = (
    "nvidia",
    "quadro",
    "rtx ",
    "rtx-",
    "blackwell",
    "epyc",
    "dgx",
    "gx10",
    "spark 1",
    "spark 2",
    "dgx spark",
    "nemix",
    "anthropic",
    "claude max",
    "xai",
    "supergrok",
    "soveryn intelligence",
    "soverynintelligence",
    "connectx",
    "asrock",
    "deco gear",
    "smttr",
    "newegg",
    "openai",
    "chatgpt",
    "tecmojo",
    "network rack",
    "server rack",
)


def classify_receipt(filename: str, text: str) -> ClassifyHit:
    name = (filename or "").lower()
    blob = f"{filename}\n{text}".lower()

    if _looks_like_quote(name, blob):
        return ClassifyHit(
            book="unsorted",
            gap="Pondwright/CWG quote is not a tax receipt — keep out of both books",
            reasons=("quote",),
        )

    # Domain SKU beats the Cloudflare payer (SOVERYN LLC often pays CWG DNS).
    if "carolinawatergardens.com" in blob and "soverynintelligence.com" not in blob:
        if "soverynintelligence.ai" not in blob:
            return ClassifyHit(book="cwg", reasons=("cwg-domain",))

    name_book = _filename_hint(name)
    cwg_hit = any(tok in blob for tok in _CWG_TEXT) or bool(_CWG_NAME.search(name))
    sov_hit = any(tok in blob for tok in _SOVERYN_TEXT) or bool(_SOVERYN_NAME.search(name))

    if name_book == "cwg" and not sov_hit:
        return ClassifyHit(book="cwg", reasons=("filename",))
    if name_book == "soveryn" and not cwg_hit:
        return ClassifyHit(book="soveryn", reasons=("filename",))
    if name_book and cwg_hit and sov_hit:
        return ClassifyHit(
            book="unsorted",
            gap="filename and body point at different entities — do not guess",
            reasons=("conflict",),
        )

    if cwg_hit and sov_hit:
        return ClassifyHit(
            book="unsorted",
            gap=(
                "both SOVERYN and CWG signals present — do not guess. "
                "Pass splits=[{book, amount, description}, ...] to split the receipt"
            ),
            reasons=("conflict",),
        )
    if cwg_hit:
        return ClassifyHit(book="cwg", reasons=("text",))
    if sov_hit:
        return ClassifyHit(book="soveryn", reasons=("text",))
    if name_book:
        return ClassifyHit(book=name_book, reasons=("filename",))
    return ClassifyHit(
        book="unsorted",
        gap="no SOVERYN or CWG signal — drop in data/intake/ledgers/soveryn or cwg, or rename the file",
        reasons=("none",),
    )


def _filename_hint(name: str) -> str | None:
    cwg = bool(_CWG_NAME.search(name))
    sov = bool(_SOVERYN_NAME.search(name))
    if cwg and sov:
        return None
    if cwg:
        return "cwg"
    if sov:
        return "soveryn"
    return None


def _looks_like_quote(name: str, blob: str) -> bool:
    if "pondwright" in blob and "quote" in blob:
        return True
    if "quote" in name and ("carolina water" in blob or "pondwright" in blob or "pond package" in blob):
        return True
    if "quote for" in blob and "carolina water" in blob:
        return True
    return False
