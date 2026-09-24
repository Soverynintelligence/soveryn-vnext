"""PDF text layer or photo OCR. Never invent page content."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from soveryn.platform.intake.pdf import ExtractResult, extract_pdf_path

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"})
RECEIPT_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}


def extract_receipt_path(path: str | Path) -> ExtractResult:
    p = Path(path)
    suf = p.suffix.lower()
    if suf == ".pdf":
        return _extract_pdf_with_fallbacks(p)
    if suf in IMAGE_SUFFIXES:
        return extract_image_path(p)
    return ExtractResult(
        status="failed",
        text="",
        page_count=0,
        pages_with_text=0,
        chars=0,
        gap=f"not a receipt file ({suf or 'no suffix'}) — PDF or photo",
        source_name=p.name,
    )


def extract_image_path(path: str | Path) -> ExtractResult:
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
        from PIL import Image
    except ImportError:
        return ExtractResult(
            status="failed",
            text="",
            page_count=0,
            pages_with_text=0,
            chars=0,
            gap="PIL not installed; cannot open receipt photo",
            source_name=p.name,
        )
    try:
        from PIL import ImageOps

        with Image.open(p) as img:
            img.load()
            oriented = ImageOps.exif_transpose(img).convert("RGB")
            page_count = 1
    except Exception as exc:  # noqa: BLE001
        return ExtractResult(
            status="failed",
            text="",
            page_count=0,
            pages_with_text=0,
            chars=0,
            gap=f"could not open image: {type(exc).__name__}: {exc}",
            source_name=p.name,
        )

    tess = _tesseract_bin()
    if tess is None:
        return ExtractResult(
            status="failed",
            text="",
            page_count=page_count,
            pages_with_text=0,
            chars=0,
            gap=(
                "photo on file but tesseract OCR is not installed. "
                "Do not invent totals. Book NEED_INVOICE from the image."
            ),
            source_name=p.name,
        )

    text = _best_ocr(oriented, tess)
    if not text:
        return ExtractResult(
            status="failed",
            text="",
            page_count=page_count,
            pages_with_text=0,
            chars=0,
            gap="OCR found no text on this photo — do not invent totals",
            source_name=p.name,
        )
    return ExtractResult(
        status="ok",
        text=text,
        page_count=page_count,
        pages_with_text=1,
        chars=len(text),
        source_name=p.name,
    )


_MONEY_HINT = re.compile(r"\$\s*\d+\.\d{2}")


def _extract_pdf_with_fallbacks(path: Path) -> ExtractResult:
    """Text layer first (pypdf, then pdftotext). Image-only PDFs go through OCR.

    Never invent page content. A Gmail printout still has a text layer —
    invoice-shaped OCR is the wrong tool for that file.
    """
    primary = extract_pdf_path(path)
    if _usable_receipt_text(primary.text):
        return primary

    poppler = _pdftotext_pdf(path)
    if poppler and _usable_receipt_text(poppler):
        pages = poppler.count("\f") + 1 if poppler.strip() else 0
        return ExtractResult(
            status="ok",
            text=poppler,
            page_count=max(pages, 1),
            pages_with_text=max(pages, 1),
            chars=len(poppler),
            source_name=path.name,
        )

    ocr = _ocr_pdf_pages(path)
    if ocr and _usable_receipt_text(ocr):
        return ExtractResult(
            status="ok",
            text=ocr,
            page_count=max(ocr.count("\f") + 1, 1),
            pages_with_text=1,
            chars=len(ocr),
            source_name=path.name,
        )

    if primary.status != "failed":
        return primary
    if poppler:
        return ExtractResult(
            status="partial",
            text=poppler,
            page_count=1,
            pages_with_text=1,
            chars=len(poppler),
            gap="PDF text layer had no labeled cash total",
            source_name=path.name,
        )
    return primary


def _usable_receipt_text(text: str | None) -> bool:
    blob = text or ""
    if len(blob.strip()) < 40:
        return False
    return bool(_MONEY_HINT.search(blob))


def _pdftotext_pdf(path: Path) -> str:
    bin_ = shutil.which("pdftotext")
    if not bin_:
        return ""
    try:
        proc = subprocess.run(
            [bin_, "-layout", str(path), "-"],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or b"").decode("utf-8", errors="replace").strip()


def _ocr_pdf_pages(path: Path) -> str:
    tess = _tesseract_bin()
    pdftoppm = shutil.which("pdftoppm")
    if tess is None or not pdftoppm:
        return ""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return ""
    tmp = Path(tempfile.mkdtemp(prefix="ledger-pdf-ocr-"))
    try:
        try:
            proc = subprocess.run(
                [pdftoppm, "-jpeg", "-r", "150", str(path), str(tmp / "page")],
                check=False,
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if proc.returncode != 0:
            return ""
        chunks: list[str] = []
        for img_path in sorted(tmp.glob("page*.jpg")):
            try:
                with Image.open(img_path) as img:
                    img.load()
                    oriented = ImageOps.exif_transpose(img).convert("RGB")
            except Exception:  # noqa: BLE001
                continue
            text = _best_ocr(oriented, tess)
            if text:
                chunks.append(text)
        return "\n".join(chunks).strip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _ocr_score(text: str) -> int:
    if not text.strip():
        return 0
    score = min(len(text), 800) // 20
    if _MONEY_HINT.search(text):
        score += 100
    upper = text.upper()
    if "AMOUNT" in upper or "TOTAL" in upper or "PAYMENT" in upper:
        score += 20
    if "SALE" in upper or "LLC" in upper:
        score += 10
    return score


def _tesseract_image(im, tess: Path, psm: int) -> str:
    fd, name = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        im.save(name, format="JPEG", quality=90)
        try:
            proc = subprocess.run(
                [str(tess), name, "stdout", "-l", "eng", "--psm", str(psm)],
                check=False,
                capture_output=True,
                timeout=45,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


def _best_ocr(im, tess: Path) -> str:
    """EXIF-upright first; if no money, try other rotations. Never invent."""
    best_text = ""
    best_score = 0
    for psm in (4, 6):
        text = _tesseract_image(im, tess, psm)
        score = _ocr_score(text)
        if score > best_score:
            best_score = score
            best_text = text
        if score >= 120:
            return text
    if best_score >= 100:
        return best_text
    for deg in (90, 270, 180):
        rot = im.rotate(deg, expand=True)
        for psm in (4, 6):
            text = _tesseract_image(rot, tess, psm)
            score = _ocr_score(text)
            if score > best_score:
                best_score = score
                best_text = text
            if score >= 120:
                return text
    return best_text


def _tesseract_bin() -> Path | None:
    env_bin = Path(sys.prefix) / "bin" / "tesseract"
    if env_bin.is_file():
        return env_bin
    found = shutil.which("tesseract")
    return Path(found) if found else None
