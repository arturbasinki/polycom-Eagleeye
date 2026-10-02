"""Each camera frame is decoded once and shared: the virtual camera writes it, the tracker
detects on it. Before, both decoded the same MJPEG frame (10.3 ms + 6.0 ms at 1080p,
measured 2026-10-02).

The planes are read-only: the light-correction table is applied to a copy for the call image,
so the tracker and the light measurement always see the raw frame.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from .jpeg import Planes, decode_yuv420


@dataclass(frozen=True)
class YuvFrame:
    frame_id: int
    y: np.ndarray       # (h, w)
    u: np.ndarray       # Cb, ((h+1)//2, (w+1)//2)
    v: np.ndarray       # Cr, same size

    def bgr_half(self) -> np.ndarray:
        """BGR at the chroma size (half of the frame) - the detector's input. Luma is reduced
        to the chroma size, chroma is used as is: one colour conversion at quarter area."""
        y = cv2.resize(self.y, (self.u.shape[1], self.u.shape[0]), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(cv2.merge((y, self.v, self.u)), cv2.COLOR_YCrCb2BGR)   # JFIF: Y, Cr, Cb


class FrameDecoder:
    """The latest decoded frame of one source. A consumer asking for a frame that another one
    is decoding waits for it instead of decoding it again."""

    def __init__(self, decode: Callable[[bytes], Planes | None] = decode_yuv420) -> None:
        self._decode = decode
        self._lock = threading.Lock()
        self._source = None          # strong reference: a new stream restarts its frame ids
        self._last: YuvFrame | None = None
        self.decoded = 0

    def get(self, source, frame_id: int, jpg: bytes) -> YuvFrame | None:
        with self._lock:
            last = self._last
            if last is not None and last.frame_id == frame_id and self._source is source:
                return last
            planes = self._decode(jpg)
            if planes is None:
                return None
            for plane in planes:
                plane.flags.writeable = False
            self._source, self._last = source, YuvFrame(frame_id, *planes)
            self.decoded += 1
            return self._last
