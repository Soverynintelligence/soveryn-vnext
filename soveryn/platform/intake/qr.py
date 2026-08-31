"""QR decode (cite-or-stop).

Uses OpenCV ``QRCodeDetector`` — already on the house tower. Never invents
a payload: an explicit miss is returned when no code is found or the
locator is visible but the payload cannot be read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Soft cap so a huge dump cannot sit in memory for one decode.
DEFAULT_MAX_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class DecodeResult:
    """Outcome of a QR decode attempt."""

    ok: bool
    payloads: tuple[str, ...]
    symbology: str | None = None
    miss: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "payloads": list(self.payloads),
            "symbology": self.symbology,
            "miss": self.miss,
        }


def decode_qr_bytes(data: bytes) -> DecodeResult:
    """Decode QR payload(s) from image bytes. Never invents content."""
    if not data:
        return DecodeResult(
            ok=False, payloads=(), symbology=None, miss="unreadable",
        )
    if len(data) > DEFAULT_MAX_BYTES:
        return DecodeResult(
            ok=False, payloads=(), symbology=None, miss="unreadable",
        )
    try:
        import cv2
        import numpy as np
    except ImportError:
        return DecodeResult(
            ok=False, payloads=(), symbology=None, miss="unreadable",
        )

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return DecodeResult(
            ok=False, payloads=(), symbology=None, miss="unreadable",
        )
    return decode_qr_image(img)


def decode_qr_image(img: Any) -> DecodeResult:
    """Decode from an OpenCV BGR/gray image. Never invents content."""
    try:
        import cv2
    except ImportError:
        return DecodeResult(
            ok=False, payloads=(), symbology=None, miss="unreadable",
        )

    payloads, detected = _try_decode(img)
    if payloads:
        return DecodeResult(ok=True, payloads=payloads, symbology="QR", miss=None)

    # Tiny module-only encodings (and some phone crops) fail at native size
    # but read after a nearest-neighbor upscale. Retry once, then stop —
    # do not guess a URL.
    h, w = img.shape[:2]
    if min(h, w) < 400:
        scale = max(2, (400 + min(h, w) - 1) // min(h, w))
        big = cv2.resize(
            img, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST,
        )
        payloads, detected_big = _try_decode(big)
        detected = detected or detected_big
        if payloads:
            return DecodeResult(
                ok=True, payloads=payloads, symbology="QR", miss=None,
            )

    if detected:
        return DecodeResult(
            ok=False, payloads=(), symbology="QR", miss="unreadable",
        )
    return DecodeResult(
        ok=False, payloads=(), symbology=None, miss="no_code_found",
    )


def _try_decode(img: Any) -> tuple[tuple[str, ...], bool]:
    """Return (payloads, locator_seen). Empty payloads are not invented."""
    import cv2

    detector = cv2.QRCodeDetector()
    detected = False
    try:
        _ok, decoded_info, points, _straight = detector.detectAndDecodeMulti(img)
    except cv2.error:
        decoded_info, points = (), None
    else:
        if points is not None and len(points) > 0:
            detected = True
        payloads = tuple(
            s for s in (decoded_info or ())
            if isinstance(s, str) and s
        )
        if payloads:
            return payloads, True

    try:
        data, pts, _straight = detector.detectAndDecode(img)
    except cv2.error:
        return (), detected
    if isinstance(data, str) and data:
        return (data,), True
    if pts is not None and len(pts) > 0:
        detected = True
    return (), detected


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DecodeResult",
    "decode_qr_bytes",
    "decode_qr_image",
]
