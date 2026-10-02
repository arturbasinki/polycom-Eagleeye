#!/usr/bin/env python3
"""MJPEG decoding to 4:2:0 planes: TurboJPEG and the Pillow fallback.

    .venv/bin/python tests/test_jpeg.py

TurboJPEG tests report "skipped" when libturbojpeg.so.0 is not installed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye import jpeg  # noqa: E402
from eagleeye.jpeg import TurboDecoder, decode_yuv420, decode_yuv420_pillow, turbo  # noqa: E402


def scene(h: int = 1080, w: int = 1920) -> np.ndarray:
    rng = np.random.default_rng(3)
    return cv2.resize(rng.integers(0, 256, (27, 48, 3), np.uint8), (w, h), interpolation=cv2.INTER_CUBIC)


def encode(img: np.ndarray, *params: int) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, list(params))
    assert ok
    return buf.tobytes()


JPG = encode(scene())                                         # OpenCV's default sampling is 4:2:0
PADDED = JPG[:-2] + b"\x00" * 40 + b"\xff\xd9"                # like the camera: padding before EOI


def stderr_of(fn):
    """Run ``fn`` and return (result, bytes written to file descriptor 2)."""
    with tempfile.TemporaryFile() as tmp:
        saved = os.dup(2)
        os.dup2(tmp.fileno(), 2)
        try:
            result = fn()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
        tmp.seek(0)
        return result, tmp.read()


def needs_turbo() -> TurboDecoder | None:
    dec = turbo()
    if dec is None:
        print("    skipped: libturbojpeg.so.0 not installed")
    return dec


def test_planes_have_420_shapes() -> None:
    y, u, v = decode_yuv420(JPG)
    assert y.shape == (1080, 1920) and u.shape == (540, 960) and v.shape == (540, 960)
    assert y.dtype == u.dtype == v.dtype == np.uint8


def test_pillow_and_turbo_luma_identical() -> None:
    dec = needs_turbo()
    if dec is None:
        return
    ty, tu, tv = dec.decode(JPG)
    py, pu, pv = decode_yuv420_pillow(JPG)
    assert np.array_equal(ty, py)
    assert np.abs(tu.astype(int) - pu).mean() < 0.5 and np.abs(tv.astype(int) - pv).mean() < 0.5


def test_camera_padding_decodes_silently() -> None:
    dec = needs_turbo()
    if dec is None:
        return
    planes, err = stderr_of(lambda: dec.decode(PADDED))
    assert planes is not None and np.array_equal(planes[0], dec.decode(JPG)[0])
    assert err == b"", err


def test_truncated_frame_is_rejected() -> None:
    cut = JPG[: len(JPG) // 2]
    assert decode_yuv420_pillow(cut) is None
    dec = turbo()
    if dec is not None:
        assert dec.decode(cut) is None
        assert dec.decode(cut + b"\xff\xd9") is None


def test_garbage_is_none() -> None:
    assert decode_yuv420(b"not a jpeg") is None
    assert decode_yuv420_pillow(b"not a jpeg") is None


def test_422_chroma_is_normalised_to_420() -> None:
    jpg = encode(scene(), cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_422)
    for planes in (decode_yuv420(jpg), decode_yuv420_pillow(jpg)):
        assert planes[1].shape == (540, 960) and planes[2].shape == (540, 960)


def test_grayscale_gets_neutral_chroma() -> None:
    jpg = encode(cv2.cvtColor(scene(360, 640), cv2.COLOR_BGR2GRAY))
    y, u, v = decode_yuv420(jpg)
    assert y.shape == (360, 640) and u.shape == (180, 320)
    assert (u == 128).all() and (v == 128).all()


def test_odd_size_chroma_rounds_up() -> None:
    y, u, _ = decode_yuv420(encode(scene(361, 641)))
    assert y.shape == (361, 641) and u.shape == (181, 321)


def test_fallback_when_library_missing() -> None:
    saved = jpeg.turbo
    jpeg.turbo = lambda: None
    try:
        y, u, v = decode_yuv420(JPG)
    finally:
        jpeg.turbo = saved
    assert y.shape == (1080, 1920) and u.shape == (540, 960)


if __name__ == "__main__":
    run(globals(), "MJPEG decoding to 4:2:0 planes")
