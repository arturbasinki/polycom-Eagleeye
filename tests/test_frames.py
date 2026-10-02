#!/usr/bin/env python3
"""One decode per camera frame, shared by the virtual camera and the tracker.

    .venv/bin/python tests/test_frames.py
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.frames import FrameDecoder, YuvFrame  # noqa: E402
from eagleeye.jpeg import decode_yuv420  # noqa: E402
from eagleeye.vcam import VirtualCamera  # noqa: E402


def encode(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


RED = encode(np.full((360, 640, 3), (0, 0, 255), np.uint8))
GREY = encode(np.full((360, 640, 3), 90, np.uint8))


class Source:
    """Stands in for a camera stream: only its identity matters to the decoder."""


def counting(calls: list):
    def decode(jpg):
        calls.append(jpg)
        return decode_yuv420(jpg)
    return decode


def test_same_frame_decodes_once() -> None:
    calls: list = []
    frames, src = FrameDecoder(counting(calls)), Source()
    first = frames.get(src, 1, GREY)
    assert isinstance(first, YuvFrame)
    assert frames.get(src, 1, GREY) is first
    assert len(calls) == 1 and frames.decoded == 1


def test_next_frame_decodes_again() -> None:
    calls: list = []
    frames, src = FrameDecoder(counting(calls)), Source()
    frames.get(src, 1, GREY)
    assert frames.get(src, 2, RED).frame_id == 2
    assert len(calls) == 2


def test_new_source_with_same_id_decodes_again() -> None:
    """A reopened stream (Resolution change) restarts its ids - never serve the old frame."""
    frames = FrameDecoder()
    old = frames.get(Source(), 1, GREY)
    new = frames.get(Source(), 1, RED)
    assert new is not old
    assert new.v.mean() > 200                     # red: high Cr


def test_damaged_frame_does_not_poison_the_cache() -> None:
    frames, src = FrameDecoder(), Source()
    good = frames.get(src, 1, GREY)
    assert frames.get(src, 2, b"broken") is None
    assert frames.get(src, 1, GREY) is good


def test_planes_are_read_only() -> None:
    frame = FrameDecoder().get(Source(), 1, GREY)
    for plane in (frame.y, frame.u, frame.v):
        assert not plane.flags.writeable


def test_concurrent_consumers_share_one_decode() -> None:
    calls: list = []

    def slow(jpg):
        calls.append(jpg)
        time.sleep(0.05)
        return decode_yuv420(jpg)

    frames, src = FrameDecoder(slow), Source()
    got: list = []
    threads = [threading.Thread(target=lambda: got.append(frames.get(src, 7, GREY))) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(calls) == 1 and got[0] is got[1]


def test_bgr_half_is_the_chroma_size_and_colour() -> None:
    frame = FrameDecoder().get(Source(), 1, RED)
    bgr = frame.bgr_half()
    assert bgr.shape == (180, 320, 3)
    b, g, r = bgr.reshape(-1, 3).mean(axis=0)
    assert r > 240 and g < 15 and b < 15


class Stream:
    actual_width, actual_height = 640, 360

    def __init__(self, jpg: bytes) -> None:
        self.jpg = jpg

    def frame_timed(self, last_id: int = 0, timeout: float = 0.0):
        return 1, self.jpg, time.monotonic()


def test_tone_does_not_change_shared_planes() -> None:
    """The light-correction table goes to the call image only; the tracker keeps the raw frame."""
    frames = FrameDecoder()
    stream = Stream(GREY)
    vc = VirtualCamera(device_factory=lambda: None, frames=frames)
    vc.set_source(stream)
    vc.set_tone(np.full(256, 255, np.uint8))     # everything white
    out = vc.current_frame()
    assert out[0] == 255
    raw = frames.get(stream, 1, GREY)            # the tracker asks for the same frame: cache hit
    assert frames.decoded == 1
    assert abs(int(raw.y.mean()) - 90) <= 2


def test_virtual_camera_and_tracker_decoder_can_be_one_object() -> None:
    frames = FrameDecoder()
    assert VirtualCamera(device_factory=lambda: None, frames=frames).frames is frames
    assert isinstance(VirtualCamera(device_factory=lambda: None).frames, FrameDecoder)


if __name__ == "__main__":
    run(globals(), "Shared frame decoding")
