"""
Strip AI provenance metadata (C2PA / Content Credentials / JUMBF) from images.

WaveSpeed and other generators embed APP11 JPEG segments that Fanvue reads
as "modified by AI". Re-encoding pixel data only removes those markers.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Tuple

# Real provenance strings only. Bare \xff\xeb (JPEG APP11) false-positives in WebP/etc.
_C2PA_STRINGS = (b"c2pa", b"jumb", b"contentauth", b"digitalsourcetype", b"trainedalgorithmicmedia")


def has_c2pa(path: str | Path) -> bool:
    raw = Path(path).read_bytes().lower()
    return any(m in raw for m in _C2PA_STRINGS)


def strip_to_temp_jpeg(
    path: str | Path,
    *,
    quality: int = 92,
) -> Tuple[str, bool]:
    """
    Return (temp_jpeg_path, source_had_c2pa).

    Always returns a clean JPEG built from RGB pixels only (no EXIF/ICC/XMP/C2PA).
    Caller must delete the temp file when done.
    """
    from PIL import Image

    src = Path(path)
    had = has_c2pa(src)

    with Image.open(src) as im:
        if im.mode in ("RGBA", "LA"):
            rgba = im.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            rgb = background
        elif im.mode == "P":
            rgba = im.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.split()[-1])
            rgb = background
        else:
            rgb = im.convert("RGB")

        # Force a pure pixel buffer so no sidecar metadata can leak through.
        pixels = list(rgb.getdata())
        size = rgb.size

    clean = Image.new("RGB", size)
    clean.putdata(pixels)

    tmp = tempfile.NamedTemporaryFile(
        suffix=".jpg", prefix=f"clean_{src.stem}_", delete=False
    )
    tmp_path = tmp.name
    tmp.close()

    clean.save(
        tmp_path,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=False,
        subsampling=0,
    )
    clean.close()

    # Sanity: cleaned file must not carry provenance strings.
    if has_c2pa(tmp_path):
        raise RuntimeError(f"C2PA markers still present after strip: {src}")

    return tmp_path, had
