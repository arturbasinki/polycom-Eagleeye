#!/usr/bin/env python3
"""Tests on the real camera (without a person in frame).

1. Watchdog: a velocity command without a refresh stops by itself.
2. Anchoring: after a velocity move, an absolute move (with the "same value"
   workaround) returns exactly to the start position - checked with the image.

Requires a free camera and a frame with texture. The position is restored.

    .venv/bin/python tests/test_tracking_live.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.actuator import Actuator  # noqa: E402
from eagleeye.detectors import decode_mjpeg  # noqa: E402
from eagleeye.geometry import View  # noqa: E402
from eagleeye.head_model import HeadModel  # noqa: E402
from eagleeye.v4l2 import (CID_PAN_SPEED, ControlDevice, MjpegStream,  # noqa: E402
                           V4L2Error)

DEVICE = "/dev/video0"
W, H = 640, 360


def gray(stream: MjpegStream, last: list[int]) -> np.ndarray:
    last[0], jpg, _ = stream.frame_timed(last[0], timeout=2.0)
    return np.float32(cv2.cvtColor(decode_mjpeg(jpg), cv2.COLOR_BGR2GRAY))


def settle(stream: MjpegStream, last: list[int], seconds: float) -> np.ndarray:
    end = time.monotonic() + seconds
    frame = gray(stream, last)
    while time.monotonic() < end:
        frame = gray(stream, last)
    return frame


def with_camera(body) -> None:
    try:
        ctl = ControlDevice(DEVICE)
        stream = MjpegStream(DEVICE, W, H)
        stream.start()
    except (OSError, V4L2Error) as exc:
        print(f"    SKIPPED: camera unavailable ({exc})")
        return
    head = HeadModel()
    act = Actuator(ctl, head)
    act.sync_from_device(time.monotonic())
    pan0 = head.angle("pan", time.monotonic())
    try:
        body(ctl, stream, act)
    finally:
        act.stop_all(time.monotonic())
        act.move_absolute("pan", pan0, time.monotonic())
        time.sleep(3.0)
        stream.stop()
        ctl.close()


def test_watchdog_stops_real_camera() -> None:
    def body(ctl, stream, act):
        act.start_watchdog()
        try:
            act.velocity("pan", 1, time.monotonic())
            time.sleep(0.8)
            assert ctl.get(CID_PAN_SPEED) == 0, "the watchdog did not zero the velocity"
        finally:
            act.stop_watchdog()
    with_camera(body)


def test_absolute_move_reanchors_after_velocity() -> None:
    def body(ctl, stream, act):
        last = [0]
        window = cv2.createHanningWindow((W, H), cv2.CV_32F)
        ref = settle(stream, last, 1.5)
        start = act.head.angle("pan", time.monotonic())
        act.velocity("pan", 1, time.monotonic())
        time.sleep(0.5)
        act.velocity("pan", 0, time.monotonic())
        time.sleep(1.5)
        act.move_absolute("pan", start, time.monotonic())     # the same value as the last write
        now = settle(stream, last, 3.0)
        (dx, _), response = cv2.phaseCorrelate(ref, now, window)
        err = abs(dx) * View(W, H).arcsec_per_px / 3600
        print(f"    return: error {err:.2f}° (confidence {response:.2f})")
        assert err < 0.3, f"the head did not return to position ({err:.2f}°)"
    with_camera(body)


if __name__ == "__main__":
    run(globals(), "Tests on the camera")
