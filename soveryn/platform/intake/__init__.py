"""House document intake — extract held text, print gaps, never invent.

v0: text-layer PDF extract. QR decode is a separate Eve desk tool.
"""

from soveryn.platform.intake.pdf import ExtractResult, extract_pdf_bytes, extract_pdf_path
from soveryn.platform.intake.qr import DecodeResult, decode_qr_bytes, decode_qr_image

__all__ = [
    "DecodeResult",
    "ExtractResult",
    "decode_qr_bytes",
    "decode_qr_image",
    "extract_pdf_bytes",
    "extract_pdf_path",
]
