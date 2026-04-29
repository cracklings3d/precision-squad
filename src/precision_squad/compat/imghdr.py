"""Minimal Python 3.14 compatibility shim for modules still importing imghdr."""

from __future__ import annotations


def what(file=None, h: bytes | None = None):
    """Infer a small set of image formats from header bytes."""
    del file
    if h is None:
        return None

    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if h.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if h.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if h.startswith(b"RIFF") and h[8:12] == b"WEBP":
        return "webp"
    if h.startswith(b"BM"):
        return "bmp"
    if h.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    return None
