"""Content inspection: detect the real type from bytes and re-encode images.

Never trusts the filename or the client-supplied Content-Type. Images are decoded with
Pillow (which rejects malformed data), orientation is applied, and the image is
re-encoded without metadata, which strips EXIF/GPS so photos cannot leak a student's location.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import UnsupportedMediaType
from app.modules.uploads.rules import JPEG, PDF, PNG, WEBP

MAX_IMAGE_PIXELS = 40_000_000  # decompression-bomb guard (~40 MP)
_SAVE_FORMAT = {JPEG: "JPEG", PNG: "PNG", WEBP: "WEBP"}


@dataclass(frozen=True, slots=True)
class InspectedContent:
    content_type: str
    data: bytes
    width: int | None
    height: int | None


def sniff(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return WEBP
    if data.startswith(b"%PDF-"):
        return PDF
    return None


def _reencode_image(data: bytes, content_type: str) -> InspectedContent:
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise UnsupportedMediaType("Image dimensions are too large.", code="IMAGE_TOO_LARGE")
            oriented = ImageOps.exif_transpose(image)
            output = io.BytesIO()
            target = _SAVE_FORMAT[content_type]
            if target == "JPEG":
                oriented = oriented.convert("RGB")
                oriented.save(output, format="JPEG", quality=85, optimize=True)
            elif target == "PNG":
                oriented.save(output, format="PNG", optimize=True)
            else:
                oriented.save(output, format="WEBP", quality=85)
            return InspectedContent(content_type, output.getvalue(), oriented.width, oriented.height)
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, ValueError) as exc:
        raise UnsupportedMediaType("The image could not be read.", code="INVALID_IMAGE") from exc


def inspect(data: bytes, allowed_types: frozenset[str]) -> InspectedContent:
    detected = sniff(data)
    if detected is None or detected not in allowed_types:
        raise UnsupportedMediaType("This file type is not allowed here.", code="UNSUPPORTED_FILE_TYPE")
    if detected == PDF:
        # PDFs (verification documents only) are stored as uploaded: never re-served publicly,
        # always with Content-Disposition: attachment.
        if b"%%EOF" not in data[-1024:]:
            raise UnsupportedMediaType("The PDF appears to be truncated.", code="INVALID_PDF")
        return InspectedContent(PDF, data, None, None)
    return _reencode_image(data, detected)
