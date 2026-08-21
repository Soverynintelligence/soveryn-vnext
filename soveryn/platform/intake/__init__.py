"""House document intake — extract held text, print gaps, never invent.

v0: text-layer PDF extract. OCR / docx / embeddings come later.
"""

from soveryn.platform.intake.pdf import ExtractResult, extract_pdf_bytes, extract_pdf_path

__all__ = [
    "ExtractResult",
    "extract_pdf_bytes",
    "extract_pdf_path",
]
