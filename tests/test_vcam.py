#!/usr/bin/env python3
"""Wirtualna kamera: konwersja klatek do I420 i plansze.

    .venv/bin/python tests/test_vcam.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.vcam import (NO_SIGNAL_TEXT, OUT_SIZE, PRIVACY_TEXT, bgr_to_i420,  # noqa: E402
                            card_i420, i420_size, jpeg_to_i420, render_card)

from eagleeye.v4l2 import OutputDevice, V4L2Error, card_name  # noqa: E402
from eagleeye.vcam import VirtualCamera  # noqa: E402

W, H = OUT_SIZE


def planes(data: bytes):
    a = np.frombuffer(data, np.uint8)
    y, u, v = a[:W * H], a[W * H:W * H * 5 // 4], a[W * H * 5 // 4:]
    return y, u, v


def test_i420_size() -> None:
    assert i420_size((1280, 720)) == 1382400


def test_red_frame_converts_to_expected_yuv() -> None:
    bgr = np.zeros((H, W, 3), np.uint8)
    bgr[:, :, 2] = 255
    y, u, v = planes(bgr_to_i420(bgr))
    assert abs(y.mean() - 76) < 3 and v.mean() > 200 and u.mean() < 110
    # BT.601: Cb czerwieni = 128 - 0.1687*255 = 85 (analogowe YUV dawało 90)
    assert abs(u.mean() - 85) < 2


def test_jpeg_is_scaled_to_output_size() -> None:
    ok, buf = cv2.imencode(".jpg", np.full((1080, 1920, 3), 90, np.uint8))
    assert ok
    assert len(jpeg_to_i420(buf.tobytes())) == i420_size(OUT_SIZE)


def test_jpeg_colors_match_bgr_reference() -> None:
    """Szybka ścieżka (JPEG wprost do YCbCr) daje te same kolory co przez BGR (BT.601)."""
    rng = np.random.default_rng(7)
    bgr = cv2.resize(rng.integers(0, 256, (27, 48, 3), np.uint8), (1920, 1080),
                     interpolation=cv2.INTER_CUBIC)
    bgr[:360, :640] = (0, 0, 255)       # czysta czerwień i biel - skraje zakresu
    bgr[:360, 640:1280] = 255
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok
    ref = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    ref = cv2.resize(ref, OUT_SIZE, interpolation=cv2.INTER_AREA)
    fast = np.frombuffer(jpeg_to_i420(buf.tobytes()), np.uint8).astype(int)
    slow = np.frombuffer(bgr_to_i420(ref), np.uint8).astype(int)
    diff = np.abs(fast - slow)
    assert diff[:W * H].mean() < 0.5 and diff[W * H:].mean() < 0.5, (diff[:W * H].mean(), diff[W * H:].mean())
    y, _, _ = planes(jpeg_to_i420(buf.tobytes()))
    assert y.reshape(H, W)[20:200, 450:800].max() >= 250    # biel w pełnym zakresie, nie 235


def test_garbage_jpeg_is_none() -> None:
    assert jpeg_to_i420(b"to nie jest jpeg") is None


def test_card_renders_text_with_polish_letters() -> None:
    card = render_card(*PRIVACY_TEXT)
    assert card.shape == (H, W, 3)
    assert (card != card[0, 0]).any(axis=2).sum() > 1000, "brak pikseli tekstu"


def test_privacy_and_no_signal_cards_differ() -> None:
    assert card_i420(*PRIVACY_TEXT) != card_i420(*NO_SIGNAL_TEXT)
    assert len(card_i420(*PRIVACY_TEXT)) == i420_size(OUT_SIZE)


class FakeDevice:
    def __init__(self, fail: bool = False) -> None:
        self.frames: list[bytes] = []
        self.fail = fail
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.fail:
            raise OSError(5, "Input/output error")
        self.frames.append(data)

    def close(self) -> None:
        self.closed = True


class FakeSource:
    """Jak MjpegStream.frame_timed: nowa klatka tylko po push()."""

    def __init__(self) -> None:
        self.n = 0
        self.jpg: bytes | None = None

    def push(self, value: int) -> None:
        ok, buf = cv2.imencode(".jpg", np.full((720, 1280, 3), value, np.uint8))
        self.n += 1
        self.jpg = buf.tobytes()

    def frame_timed(self, last_id: int = 0, timeout: float = 2.0):
        return self.n, self.jpg, 0.0


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def rig(device=None, factory=None):
    clock = Clock()
    dev = device if device is not None else FakeDevice()
    vc = VirtualCamera(device_factory=factory or (lambda: dev), clock=clock)
    return vc, dev, clock


def test_privacy_sends_privacy_card() -> None:
    vc, dev, _ = rig()
    vc.set_privacy(True)
    vc.tick()
    assert dev.frames == [card_i420(*PRIVACY_TEXT)] and vc.status == "działa"


def test_live_frame_is_converted_and_repeated() -> None:
    vc, dev, clock = rig()
    src = FakeSource()
    src.push(120)
    vc.set_source(src)
    vc.tick()
    clock.t += 0.033
    vc.tick()
    assert len(dev.frames) == 2 and dev.frames[0] == dev.frames[1]
    y = np.frombuffer(dev.frames[0], np.uint8)[:1280 * 720]
    assert abs(y.mean() - 120) < 3


def test_stale_source_switches_to_no_signal() -> None:
    vc, dev, clock = rig()
    src = FakeSource()
    src.push(120)
    vc.set_source(src)
    vc.tick()
    clock.t += 1.5
    vc.tick()
    assert dev.frames[-1] == card_i420(*NO_SIGNAL_TEXT)


def test_no_source_sends_no_signal() -> None:
    vc, dev, _ = rig()
    vc.tick()
    assert dev.frames == [card_i420(*NO_SIGNAL_TEXT)]


def test_missing_device_reports_status_and_retries_later() -> None:
    calls = []

    def factory():
        calls.append(1)
        return None
    vc, _, clock = rig(factory=factory)
    vc.tick()
    vc.tick()
    assert len(calls) == 1 and "install.sh" in vc.status
    clock.t += VirtualCamera.RETRY_S + 0.1
    vc.tick()
    assert len(calls) == 2


def test_write_error_closes_and_retries() -> None:
    bad = FakeDevice(fail=True)
    vc, _, _ = rig(device=bad)
    vc.tick()
    assert bad.closed and vc.status.startswith("błąd zapisu")


def test_thread_writes_at_steady_rate() -> None:
    dev = FakeDevice()
    vc = VirtualCamera(device_factory=lambda: dev)
    vc.start()
    time.sleep(1.0)
    vc.stop()
    assert 25 <= len(dev.frames) <= 35, len(dev.frames)
    assert vc.status == "wyłączona"


def test_output_device_rejects_non_video_node() -> None:
    try:
        OutputDevice("/dev/null", (1280, 720)).open()
    except V4L2Error:
        return
    raise AssertionError("oczekiwano V4L2Error")


def test_card_name_of_non_video_node_is_none() -> None:
    assert card_name("/dev/null") is None


if __name__ == "__main__":
    run(globals(), "Wirtualna kamera: klatki i plansze")
