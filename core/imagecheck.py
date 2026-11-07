"""Image format sniffing and blank-frame detection.

Both functions are ported unchanged in behaviour from spike/spike_cloudflare.py,
where they were validated against 20 real generations with zero false positives.

Why these exist at all:

* `content-type` LIES. SDXL-Lightning declares `image/png` and returns JPEG;
  klein-4b also returns JPEG. The extension must come from magic bytes.

* Cloudflare's content filter does NOT return an error. A blocked prompt comes
  back HTTP 200 with a byte-identical all-black frame. Without `is_blank()` an
  overnight batch would save hundreds of black images and report 100% success.
"""

from __future__ import annotations

import io

# magic -> extension
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)


def sniff_ext(data: bytes) -> str:
    """Pick a file extension from magic bytes.

    MEASURED: the declared content-type is unreliable — never trust it, and
    never hardcode '.png'.
    """
    for magic, ext in _MAGIC:
        if data[: len(magic)] == magic:
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def is_blank(data: bytes) -> bool:
    """True if the image is a single flat colour (in practice: all black).

    This is what Cloudflare's content filter looks like: HTTP 200 with a
    hardcoded black frame, no error field and no distinct status code.

    Returns False if the bytes cannot be decoded at all — that is a *corrupt*
    response, a different (and retryable) failure, so it must not be
    misreported as a content block.
    """
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return False
    return all(lo == hi for lo, hi in im.getextrema())


def decodes(data: bytes) -> bool:
    """True if the bytes are a decodable image. Used to separate a truncated
    or garbage response (retryable) from a valid but blocked one."""
    try:
        from PIL import Image

        Image.open(io.BytesIO(data)).verify()
        return True
    except Exception:
        return False


def dimensions(data: bytes) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Optional local format conversion.
#
# The provider sends whatever it sends -- and lies about it in the header, so
# `sniff_ext` remains the only trustworthy source for what actually arrived.
# Converting is therefore a LOCAL, post-download step, never a request
# parameter. Kept opt-in: re-encoding a JPEG as a PNG cannot recover detail the
# JPEG already discarded, it only makes a bigger file.
# ---------------------------------------------------------------------------

# Formats worth offering.
#
# WebP is deliberately NOT here. It is poorly supported by image viewers and
# editors, so anyone receiving one tends to convert it straight back -- and a
# JPEG -> WebP -> JPEG round trip measured up to 36/255 channel drift, i.e.
# real quality loss for no benefit. Offering a format whose normal fate is
# being converted again would be actively unhelpful.
CONVERT_FORMATS: dict[str, str] = {
    "keep": "Keep original (recommended)",
    "png": "PNG - lossless container, much larger",
    "jpg": "JPEG - smaller files, opens anywhere",
}


def convert_image(data: bytes, target: str, quality: int = 95) -> tuple[bytes, str]:
    """Re-encode `data` as `target`. Returns (bytes, extension).

    Falls back to the original bytes if the conversion fails for any reason --
    a batch must never lose a generated image because a format switch went
    wrong.
    """
    target = (target or "keep").lower().lstrip(".")
    if target in ("", "keep", "original"):
        return data, sniff_ext(data)

    current = sniff_ext(data).lstrip(".")
    if current == target or (target == "jpeg" and current == "jpg"):
        return data, sniff_ext(data)

    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        buf = io.BytesIO()
        if target in ("jpg", "jpeg"):
            # JPEG has no alpha channel; flatten onto white rather than
            # letting Pillow raise.
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                flat = Image.new("RGB", im.size, (255, 255, 255))
                flat.paste(im, mask=im.split()[-1])
                im = flat
            else:
                im = im.convert("RGB")
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            return buf.getvalue(), ".jpg"
        if target == "png":
            im.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), ".png"
    except Exception:
        pass
    return data, sniff_ext(data)
