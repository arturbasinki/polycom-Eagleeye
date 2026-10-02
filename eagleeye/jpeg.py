"""MJPEG frames decoded straight to 4:2:0 planes (Y, Cb, Cr) - what the virtual camera
writes and what the tracker converts for the detector.

A JPEG already stores Y, Cb and Cr. TurboJPEG hands them out as they are: no RGB, no chroma
upsampling and re-downsampling. Measured on a 1080p camera frame (2026-10-02): 3.7 ms instead
of 8.5 ms for Pillow's YCbCr decode (10.3 ms with the split and chroma resize after it).
Luma is byte-identical to Pillow's.

``libturbojpeg.so.0`` (Ubuntu ``libturbojpeg0``, installed by install.sh) through ``ctypes``
and the TurboJPEG 2.x API, which 3.x keeps. Without it: Pillow, one warning in the log.
Not OpenCV: its libjpeg prints ``Corrupt JPEG data`` to stderr on every frame of this camera,
which pads frames before the EOI marker (still true in OpenCV 5.0).
"""

from __future__ import annotations

import ctypes
import functools
import io
import logging
import threading
import warnings
from ctypes import POINTER, byref, c_char_p, c_int, c_ulong, c_void_p

import cv2
import numpy as np
from PIL import Image

log = logging.getLogger("eagleeye")

Planes = tuple[np.ndarray, np.ndarray, np.ndarray]

TJSAMP_GRAY = 3
TJERR_WARNING = 0
# The camera pads frames before EOI; libjpeg calls it a warning. Any other warning (truncated
# data) means a damaged frame, which we drop so the virtual camera repeats the last good one.
PADDING_WARNING = b"extraneous bytes"


def _to_420(y: np.ndarray, u: np.ndarray, v: np.ndarray) -> Planes:
    """Chroma at half size in both directions; 4:2:2 and 4:4:4 frames are reduced."""
    h, w = y.shape
    half = ((w + 1) // 2, (h + 1) // 2)
    if (u.shape[1], u.shape[0]) != half:
        u = cv2.resize(u, half, interpolation=cv2.INTER_AREA)
        v = cv2.resize(v, half, interpolation=cv2.INTER_AREA)
    return y, u, v


class TurboDecoder:
    """One TurboJPEG decompressor; calls are serialised (a handle is not thread-safe)."""

    def __init__(self, lib) -> None:
        lib.tjInitDecompress.restype = c_void_p
        lib.tjDecompressHeader3.argtypes = [c_void_p, c_char_p, c_ulong] + [POINTER(c_int)] * 4
        lib.tjDecompressToYUVPlanes.argtypes = [c_void_p, c_char_p, c_ulong, POINTER(c_void_p),
                                                c_int, POINTER(c_int), c_int, c_int]
        lib.tjPlaneWidth.argtypes = lib.tjPlaneHeight.argtypes = [c_int, c_int, c_int]
        lib.tjGetErrorCode.argtypes = [c_void_p]
        lib.tjGetErrorStr2.argtypes = [c_void_p]
        lib.tjGetErrorStr2.restype = c_char_p
        self._lib = lib
        self._handle = lib.tjInitDecompress()
        self._lock = threading.Lock()

    @classmethod
    def load(cls) -> TurboDecoder | None:
        try:
            return cls(ctypes.CDLL("libturbojpeg.so.0"))
        except (OSError, AttributeError):
            return None

    def decode(self, jpg: bytes) -> Planes | None:
        lib = self._lib
        with self._lock:
            w, h, sub, space = c_int(), c_int(), c_int(), c_int()
            if lib.tjDecompressHeader3(self._handle, jpg, len(jpg), byref(w), byref(h),
                                       byref(sub), byref(space)) != 0:
                return None
            count = 1 if sub.value == TJSAMP_GRAY else 3
            planes = [np.empty((lib.tjPlaneHeight(i, h.value, sub.value),
                                lib.tjPlaneWidth(i, w.value, sub.value)), np.uint8) for i in range(count)]
            pointers = (c_void_p * 3)(*(p.ctypes.data for p in planes), *([None] * (3 - count)))
            if lib.tjDecompressToYUVPlanes(self._handle, jpg, len(jpg), pointers, w.value, None,
                                           h.value, 0) != 0:
                if (lib.tjGetErrorCode(self._handle) != TJERR_WARNING
                        or PADDING_WARNING not in lib.tjGetErrorStr2(self._handle)):
                    return None
        # TurboJPEG pads the luma plane up to an even size for subsampled formats and reports
        # the frame's real size in the header; crop back to it so the planes are exactly the
        # camera's frame (chroma is already ceil(size/2); _to_420 reduces 4:2:2/4:4:4).
        planes[0] = planes[0][:h.value, :w.value]
        if count == 1:
            half = ((h.value + 1) // 2, (w.value + 1) // 2)
            planes += [np.full(half, 128, np.uint8), np.full(half, 128, np.uint8)]
        return _to_420(*planes)


@functools.cache
def turbo() -> TurboDecoder | None:
    decoder = TurboDecoder.load()
    if decoder is None:
        log.warning("libturbojpeg.so.0 not found - decoding MJPEG with Pillow, which costs "
                    "about twice the CPU (install the libturbojpeg0 package)")
    return decoder


def decode_yuv420_pillow(jpg: bytes) -> Planes | None:
    """The fallback: Pillow decodes to interleaved YCbCr (chroma upsampled), we split it and
    reduce the chroma again. Same luma as TurboJPEG, about twice the time."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(io.BytesIO(jpg)) as image:
                image.draft("YCbCr", image.size)
                ycc = np.asarray(image if image.mode == "YCbCr" else image.convert("YCbCr"))
    except Exception:
        return None
    return _to_420(*cv2.split(ycc))


def decode_yuv420(jpg: bytes) -> Planes | None:
    """An MJPEG frame as (Y, Cb, Cr) planes at 4:2:0, or None when it is damaged."""
    decoder = turbo()
    return decoder.decode(jpg) if decoder is not None else decode_yuv420_pillow(jpg)
