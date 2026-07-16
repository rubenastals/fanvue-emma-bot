"""
Strip AI provenance metadata (C2PA / Content Credentials / JUMBF) from images.

WaveSpeed and other generators embed APP11 JPEG segments that Fanvue reads
as "modified by AI". Re-encoding pixel data only removes those markers.
"""
from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Optional, Tuple

_C2PA_MARKERS = (b"c2pa", b"jumb", b"contentauth", b"\xff\xeb")


def has_c2pa(path: str | Path) -> bool:
    raw = Path(path).read_bytes()
    return any(m in raw for m in _C2PA_MARKERS)


def strip_to_temp_jpeg(
    path: str | Path,
    *,
    quality: int = 95,
) -> Tuple[str, bool]:
    """
    Return (temp_jpeg_path, was_stripped).

    Always returns a clean JPEG without EXIF/C2PA/APP segments.
    Caller must delete the temp file when done.
    """
    from PIL import Image

    src = Path(path)
    had = has_c2pa(src)
    img = Image.open(src)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background
    else:
        img = img.convert("RGB")

    tmp = tempfile.NamedTemporaryFile(
        suffix=".jpg", prefix=f"clean_{src.stem}_", delete=False
    )
    tmp_path = tmp.name
    tmp.close()
    img.save(tmp_path, format="JPEG", quality=quality, optimize=True)
    return tmp_path, had
