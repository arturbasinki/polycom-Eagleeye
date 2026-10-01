#!/usr/bin/env python3
"""Virtual camera: frame conversion to I420 and the slates.

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

from eagleeye.i18n import msg  # noqa: E402
from eagleeye.vcam import (NO_SIGNAL_CARD, OUT_SIZE, PRIVACY_CARD, bgr_to_i420,  # noqa: E402
                            card_i420, card_texts, i420_size, i420_to_jpeg, jpeg_to_i420, render_card)

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
    # BT.601: red Cb = 128 - 0.1687*255 = 85 (analog YUV gave 90)
    assert abs(u.mean() - 85) < 2


def test_jpeg_is_scaled_to_output_size() -> None:
    ok, buf = cv2.imencode(".jpg", np.full((1080, 1920, 3), 90, np.uint8))
    assert ok
    assert len(jpeg_to_i420(buf.tobytes())) == i420_size(OUT_SIZE)


def test_jpeg_colors_match_bgr_reference() -> None:
    """The fast path (JPEG straight to YCbCr) gives the same colors as through BGR (BT.601)."""
    rng = np.random.default_rng(7)
    bgr = cv2.resize(rng.integers(0, 256, (27, 48, 3), np.uint8), (1920, 1080),
                     interpolation=cv2.INTER_CUBIC)
    bgr[:360, :640] = (0, 0, 255)       # pure red and white - the range extremes
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
    assert y.reshape(H, W)[20:200, 450:800].max() >= 250    # white at full range, not 235


def test_garbage_jpeg_is_none() -> None:
    assert jpeg_to_i420(b"this is not jpeg") is None


def test_card_renders_text_with_polish_letters() -> None:
    card = render_card(*card_texts(PRIVACY_CARD))
    assert card.shape == (H, W, 3)
    assert (card != card[0, 0]).any(axis=2).sum() > 1000, "no text pixels"


def test_privacy_and_no_signal_cards_differ() -> None:
    assert card_i420(*card_texts(PRIVACY_CARD)) != card_i420(*card_texts(NO_SIGNAL_CARD))
    assert len(card_i420(*card_texts(PRIVACY_CARD))) == i420_size(OUT_SIZE)


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
    """Like MjpegStream.frame_timed: a new frame only after push()."""

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
    assert dev.frames == [card_i420(*card_texts(PRIVACY_CARD))] and vc.status == msg("vcam.status.running")


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
    assert dev.frames[-1] == card_i420(*card_texts(NO_SIGNAL_CARD))


def test_no_source_sends_no_signal() -> None:
    vc, dev, _ = rig()
    vc.tick()
    assert dev.frames == [card_i420(*card_texts(NO_SIGNAL_CARD))]


def test_missing_device_reports_status_and_retries_later() -> None:
    calls = []

    def factory():
        calls.append(1)
        return None
    vc, _, clock = rig(factory=factory)
    vc.tick()
    vc.tick()
    assert len(calls) == 1 and vc.status == msg("vcam.status.no_device")
    clock.t += VirtualCamera.RETRY_S + 0.1
    vc.tick()
    assert len(calls) == 2


def test_write_error_closes_and_retries() -> None:
    bad = FakeDevice(fail=True)
    vc, _, _ = rig(device=bad)
    vc.tick()
    assert bad.closed and vc.status.key == "vcam.status.write_error"


def test_thread_writes_at_steady_rate() -> None:
    dev = FakeDevice()
    vc = VirtualCamera(device_factory=lambda: dev)
    vc.start()
    time.sleep(1.0)
    vc.stop()
    assert 25 <= len(dev.frames) <= 35, len(dev.frames)
    assert vc.status == msg("vcam.status.off")


def test_slates_fit_the_card_in_every_language() -> None:
    from PIL import ImageFont

    from eagleeye import i18n
    from eagleeye.placeholder import OFF_CARD
    from eagleeye.vcam import (FONT_BOLD_PATH, FONT_PATH, NO_SIGNAL_CARD, OUT_SIZE,
                               PRIVACY_CARD)
    w, h = OUT_SIZE
    title_font = ImageFont.truetype(str(FONT_BOLD_PATH), h // 12)
    subtitle_font = ImageFont.truetype(str(FONT_PATH), h // 28)
    try:
        for language in i18n.available_languages():
            i18n.set_language(language)
            for card in (PRIVACY_CARD, NO_SIGNAL_CARD, OFF_CARD):
                title, subtitle = card_texts(card)
                assert title_font.getlength(title) <= 0.9 * w, (language, title)
                assert subtitle_font.getlength(subtitle) <= 0.9 * w, (language, subtitle)
    finally:
        i18n.set_language("en")


def test_refresh_language_rerenders_the_cards() -> None:
    from eagleeye import i18n
    vc = VirtualCamera(device_factory=lambda: None, size=(320, 180))
    try:
        i18n.set_language("en")
        vc.refresh_language()
        english = vc._card_privacy
        i18n.set_language("pl")
        vc.refresh_language()
        assert vc._card_privacy != english
    finally:
        i18n.set_language("en")


def test_output_device_rejects_non_video_node() -> None:
    try:
        OutputDevice("/dev/null", (1280, 720)).open()
    except V4L2Error:
        return
    raise AssertionError("expected V4L2Error")


def test_card_name_of_non_video_node_is_none() -> None:
    assert card_name("/dev/null") is None


def _gamma_table(exponent: float) -> np.ndarray:
    return (255.0 * (np.arange(256) / 255.0) ** exponent).astype(np.uint8)


def test_tone_table_changes_only_the_luma_plane() -> None:
    ok, buf = cv2.imencode(".jpg", np.full((720, 1280, 3), (90, 140, 200), np.uint8))
    jpg = buf.tobytes()
    plain = jpeg_to_i420(jpg)
    tuned = jpeg_to_i420(jpg, lut=_gamma_table(0.5))
    y0, u0, v0 = planes(plain)
    y1, u1, v1 = planes(tuned)
    assert y1.mean() > y0.mean() + 20
    assert np.array_equal(u0, u1) and np.array_equal(v0, v1)


def test_virtual_camera_applies_the_tone_table_but_never_to_slates() -> None:
    vc, dev, clock = rig()
    src = FakeSource()
    src.push(60)
    vc.set_source(src)
    vc.tick()
    plain = planes(dev.frames[-1])[0].mean()
    vc.set_tone(_gamma_table(0.5))
    clock.t += 0.033
    vc.tick()                                              # same camera frame, converted again with the table
    assert planes(dev.frames[-1])[0].mean() > plain + 20
    vc.set_privacy(True)
    vc.tick()
    assert dev.frames[-1] == card_i420(*card_texts(PRIVACY_CARD))
    vc.set_privacy(False)
    vc.set_tone(None)
    clock.t += 0.033
    vc.tick()
    assert abs(planes(dev.frames[-1])[0].mean() - plain) < 1


def test_i420_to_jpeg_keeps_the_colours() -> None:
    bgr = np.zeros((720, 1280, 3), np.uint8)
    bgr[:] = (90, 140, 200)
    jpg = i420_to_jpeg(bgr_to_i420(bgr))
    assert jpg is not None
    back = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    assert back.shape == bgr.shape
    assert np.abs(back.astype(int) - bgr.astype(int)).max() <= 6


def test_i420_to_jpeg_rejects_data_of_the_wrong_size() -> None:
    assert i420_to_jpeg(b"abc") is None


def test_live_frame_is_the_corrected_frame_and_goes_stale() -> None:
    vc, dev, clock = rig()
    src = FakeSource()
    src.push(60)
    vc.set_source(src)
    assert vc.live_frame() is None                         # nothing converted yet
    vc.tick()
    plain = vc.live_frame()
    assert plain is not None and len(plain) == i420_size(OUT_SIZE)
    vc.set_tone(_gamma_table(0.5))
    clock.t += 0.033
    vc.tick()
    corrected = vc.live_frame()
    assert planes(corrected)[0].mean() > planes(plain)[0].mean() + 20
    clock.t += 2.0
    assert vc.live_frame() is None                         # no new camera frame: the preview falls back to raw


def test_output_size_follows_the_source_and_reopens_the_device() -> None:
    dev = FakeDevice()
    clock = Clock()
    opened: list[tuple[int, int]] = []
    vc = VirtualCamera(device_factory=lambda: (opened.append(vc.size), dev)[1], clock=clock)
    big = FakeSource()
    big.push(120)
    big.actual_width, big.actual_height = 1920, 1080
    vc.set_source(big)
    vc.tick()
    assert vc.size == (1920, 1080) and opened == [(1920, 1080)]
    assert len(dev.frames[-1]) == i420_size((1920, 1080))
    small = FakeSource()
    small.push(120)
    small.actual_width, small.actual_height = 640, 360
    vc.set_source(small)
    vc.tick()
    assert vc.size == (640, 360) and opened[-1] == (640, 360) and dev.closed
    assert len(dev.frames[-1]) == i420_size((640, 360))
    vc.set_privacy(True)
    vc.tick()
    assert len(dev.frames[-1]) == i420_size((640, 360))            # the slates follow the size too


if __name__ == "__main__":
    run(globals(), "Virtual camera: frames and slates")
