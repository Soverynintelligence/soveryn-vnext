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


_MONEY_HINT = re.compile(
    r"\$\s*\d+\.\d{2}"
    r"|(?:grand\s+total|amount(?:\s+(?:due|paid))?|payment\s+amount|"
    r"subtotal|total(?:\s+tax)?)\s*:?\s*-?\s*\$?\s*\d+\.\d{2}",
    re.I,
)


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
    money_hits = list(_MONEY_HINT.finditer(text))
    if money_hits:
        score += 60 + 20 * min(len(money_hits), 4)
    upper = text.upper()
    if "TOTAL TAX" in upper:
        score += 40
    if re.search(r"\bINVOICE\s+\d+", upper):
        score += 15
    if re.search(r"\bA[HNM]OUNT\s*:?\s*\d+\.\d{2}", upper):
        score += 20
    if "AMOUNT" in upper or "TOTAL" in upper or "PAYMENT" in upper:
        score += 20
    if "SALE" in upper or "LLC" in upper:
        score += 10
    if re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", text):
        score += 10
    if re.search(r"\b\d+\.\s*$", text.strip()):
        score -= 15
    if len(text) > 900:
        score -= 25
    return score


def _paper_crop(im):
    """Crop to bright thermal paper on a dark snap. Original if no paper."""
    from PIL import ImageOps

    gray = ImageOps.grayscale(im)
    bw = gray.point(lambda p: 255 if p > 210 else 0)
    bbox = bw.getbbox()
    if not bbox:
        return im
    x0, y0, x1, y1 = bbox
    width, height = im.size
    box_w, box_h = x1 - x0, y1 - y0
    if box_w < width * 0.25 or box_h < height * 0.25:
        return im
    if box_w > width * 0.98 and box_h > height * 0.98:
        return im
    pad = 16
    return im.crop(
        (
            max(0, x0 - pad),
            max(0, y0 - pad),
            min(width, x1 + pad),
            min(height, y1 + pad),
        )
    )


def _enhance_for_ocr(im):
    """Upscale small snaps and stretch contrast. In-memory only; not evidence."""
    from PIL import Image, ImageOps

    gray = ImageOps.grayscale(im)
    width, height = gray.size
    if max(width, height) < 1800:
        gray = gray.resize(
            (int(width * 2), int(height * 2)), Image.Resampling.LANCZOS
        )
    return ImageOps.autocontrast(gray).convert("RGB")


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
    """EXIF-upright, paper crop, contrast. Rotations only if no money. Never invent."""
    cropped = _paper_crop(im)
    variants = [im]
    if cropped.size != im.size:
        variants.append(cropped)
    variants.append(_enhance_for_ocr(cropped))

    best_text = ""
    best_score = 0
    for variant in variants:
        for psm in (4, 6):
            text = _tesseract_image(variant, tess, psm)
            score = _ocr_score(text)
            if score > best_score:
                best_score = score
                best_text = text
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
