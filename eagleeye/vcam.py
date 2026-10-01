"""Virtual camera "EagleEye": the application's image as a camera for Meet, Teams and OBS.

The device comes from the v4l2loopback module (installer: card_label="EagleEye",
exclusive_caps=1). We write raw I420 (YU12) 1280x720 frames at a steady
30 fps - receivers see an even stream regardless of camera pauses.
When there is no image (privacy, camera disconnected), we write a slate.
"""

from __future__ import annotations

import io
import logging
import math
import threading
import time
import warnings
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .i18n import msg, t
from .v4l2 import OutputDevice, V4L2Error, find_device_by_card

log = logging.getLogger("eagleeye")

CARD_LABEL = "EagleEye"
OUT_SIZE = (1280, 720)
OUT_FPS = 30.0
FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
CARD_BG_RGB = (18, 22, 28)
PRIVACY_CARD = ("vcam.card.privacy.title", "vcam.card.privacy.subtitle")
NO_SIGNAL_CARD = ("vcam.card.no_signal.title", "vcam.card.no_signal.subtitle")


def card_texts(card: tuple[str, str]) -> tuple[str, str]:
    """Title and subtitle of a slate in the active language."""
    return t(card[0]), t(card[1])


def i420_size(size: tuple[int, int]) -> int:
    w, h = size
    return w * h * 3 // 2


def bgr_to_i420(bgr: np.ndarray) -> bytes:
    """BGR (h, w, 3) -> I420: the Y plane, then U and V at quarter resolution.

    Full ranges (Y 0-255) - that is what Meet and OBS expect. ``COLOR_BGR2YUV_I420``
    in OpenCV 5.0 gives luma in the limited range (16-235), so we pack the planes
    ourselves. BT.601 coefficients (``YCrCb``, as in JPEG), not ``BGR2YUV``
    - that is analog YUV (U 0.492, V 0.877), which oversaturated reds by 23%.
    """
    y, cr, cb = cv2.split(cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb))
    h, w = bgr.shape[:2]
    u = cv2.resize(cb, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    v = cv2.resize(cr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    return b"".join((y.tobytes(), u.tobytes(), v.tobytes()))


def jpeg_to_i420(jpg: bytes, size: tuple[int, int] = OUT_SIZE,
                 lut: np.ndarray | None = None) -> bytes | None:
    """MJPEG frame -> I420 without going through RGB.

    JPEG stores the image as full-range YCbCr (JFIF), which is exactly
    what the output wants - so we decode straight to YCbCr instead of
    YCbCr -> RGB -> YUV. Measured on a 1080p frame: 26 ms CPU instead of 67 ms.
    Pillow, not ``cv2.imdecode`` - the reason is in :func:`decode_mjpeg`.
    ``lut`` is an optional 256-entry table applied to the luma plane (light correction).
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with Image.open(io.BytesIO(jpg)) as image:
                image.draft("YCbCr", image.size)
                ycc = np.asarray(image if image.mode == "YCbCr" else image.convert("YCbCr"))
    except Exception:
        return None
    w, h = size
    if (ycc.shape[1], ycc.shape[0]) != (w, h):
        ycc = cv2.resize(ycc, (w, h), interpolation=cv2.INTER_AREA)
    y, u, v = cv2.split(ycc)
    if lut is not None:
        y = cv2.LUT(y, lut)
    u = cv2.resize(u, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    v = cv2.resize(v, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    return b"".join((y.tobytes(), u.tobytes(), v.tobytes()))


def i420_to_jpeg(data: bytes, size: tuple[int, int] = OUT_SIZE, quality: int = 85) -> bytes | None:
    """The virtual camera's I420 frame as a JPEG - for the in-app preview while a light correction
    is active. The frame was already decoded and corrected for the output, so showing it costs one
    encode (~3.5 ms at 1280x720) instead of decode + table + encode of the camera frame (~32 ms at
    1080p, measured). Full-range planes, as written by :func:`bgr_to_i420` and :func:`jpeg_to_i420`."""
    w, h = size
    if len(data) != i420_size(size):
        return None
    a = np.frombuffer(data, np.uint8)
    y = a[:w * h].reshape(h, w)
    u = a[w * h:w * h * 5 // 4].reshape(h // 2, w // 2)
    v = a[w * h * 5 // 4:].reshape(h // 2, w // 2)
    ycc = cv2.merge((y, cv2.resize(v, (w, h), interpolation=cv2.INTER_LINEAR),     # JFIF order: Y, Cr, Cb
                     cv2.resize(u, (w, h), interpolation=cv2.INTER_LINEAR)))
    ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(ycc, cv2.COLOR_YCrCb2BGR),
                               [cv2.IMWRITE_JPEG_QUALITY, quality])
    return encoded.tobytes() if ok else None


def _font(path: Path, px: int):
    try:
        return ImageFont.truetype(str(path), px)
    except OSError:
        return ImageFont.load_default()


def render_card(title: str, subtitle: str = "", size: tuple[int, int] = OUT_SIZE) -> np.ndarray:
    """Slate: dark background, centered title and subtitle. Pillow, because OpenCV fonts
    have no Polish characters. Returns a BGR image."""
    w, h = size
    img = Image.new("RGB", (w, h), CARD_BG_RGB)
    draw = ImageDraw.Draw(img)
    lines = ((title, _font(FONT_BOLD_PATH, h // 12), (230, 237, 243), -h // 24),
             (subtitle, _font(FONT_PATH, h // 28), (139, 148, 158), h // 16))
    for text, font, color, dy in lines:
        if not text:
            continue
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        x = (w - (right - left)) / 2 - left
        y = h / 2 + dy - (bottom - top) / 2 - top
        draw.text((x, y), text, font=font, fill=color)
    return np.ascontiguousarray(np.asarray(img)[:, :, ::-1])


def card_i420(title: str, subtitle: str = "", size: tuple[int, int] = OUT_SIZE) -> bytes:
    return bgr_to_i420(render_card(title, subtitle, size))


def open_loopback(card: str = CARD_LABEL, size: tuple[int, int] = OUT_SIZE) -> OutputDevice | None:
    """Opens the "EagleEye" device as an output; None when the module/device is missing."""
    path = find_device_by_card(card)
    return OutputDevice(path, size).open() if path else None


class VirtualCamera:
    """A thread writing the current output frame at a steady rate.

    Output frame: the privacy slate, the last camera frame (repeated until a new
    one arrives) or the "no signal" slate when there has been no new frame for
    longer than ``STALE_S``. A missing device or a write error does not stop
    work - the next attempt comes after ``RETRY_S``.
    """

    RETRY_S = 1.0         # also taking the device over from the placeholder at startup
    STALE_S = 1.0

    def __init__(self, device_factory: Callable[[], OutputDevice | None] | None = None,
                 size: tuple[int, int] = OUT_SIZE, fps: float = OUT_FPS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._factory = device_factory or (lambda: open_loopback(CARD_LABEL, self.size))
        self.size = (int(size[0]), int(size[1]))
        self._resize_pending = False
        self.fps = fps
        self._clock = clock
        self._source = None
        self._last_id = 0
        self._live: bytes | None = None
        self._live_at = -math.inf
        self._privacy = False
        self._tone: np.ndarray | None = None      # light-correction table for the luma plane
        self._card_privacy = self._card_no_signal = b""
        self.refresh_language()
        self._device = None
        self._retry_at = -math.inf
        self.status = msg("vcam.status.off")
        self.frames_written = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def refresh_language(self) -> None:
        """Re-render the slates in the active UI language (called when the language changes)."""
        self._card_privacy = card_i420(*card_texts(PRIVACY_CARD), size=self.size)
        self._card_no_signal = card_i420(*card_texts(NO_SIGNAL_CARD), size=self.size)

    def set_source(self, stream) -> None:
        """Connect the camera stream. The output follows the stream's size (the "Resolution" setting):
        a different size re-renders the slates and reopens the output device at that size."""
        width = getattr(stream, "actual_width", 0) or 0
        height = getattr(stream, "actual_height", 0) or 0
        new_size = (width - width % 2, height - height % 2)      # I420 needs even dimensions
        with self._lock:
            self._source = stream
            self._last_id = 0
            self._live = None
            changed = min(new_size) > 0 and new_size != self.size
            if changed:
                self.size = new_size
                self._resize_pending = True
        if changed:
            self.refresh_language()

    def set_privacy(self, on: bool) -> None:
        self._privacy = bool(on)

    @property
    def privacy(self) -> bool:
        return self._privacy

    def set_tone(self, lut: np.ndarray | None) -> None:
        """Light-correction table (256 x uint8) for live frames; None removes it. Slates are never
        corrected. The latest camera frame is converted again on the next write."""
        with self._lock:
            self._tone = None if lut is None else np.ascontiguousarray(lut, dtype=np.uint8)
            self._last_id = 0

    def live_frame(self) -> bytes | None:
        """The latest converted camera frame (I420, light-correction table applied), or None when
        there is none or it is stale. The in-app preview shows this while a correction is active."""
        with self._lock:
            if self._live is None or self._clock() - self._live_at > self.STALE_S:
                return None
            return self._live

    def current_frame(self) -> bytes:
        if self._privacy:
            return self._card_privacy
        with self._lock:
            source = self._source
            if source is not None:
                frame_id, jpg, _ = source.frame_timed(self._last_id, timeout=0.0)
                if jpg is not None and frame_id != self._last_id:
                    data = jpeg_to_i420(jpg, self.size, self._tone)
                    if data is not None:
                        self._last_id, self._live, self._live_at = frame_id, data, self._clock()
            live, live_at = self._live, self._live_at
        if live is None or self._clock() - live_at > self.STALE_S:
            return self._card_no_signal
        return live

    def tick(self) -> None:
        """One write: opens the device if needed and sends the current frame."""
        now = self._clock()
        if self._resize_pending:
            self._resize_pending = False
            if self._device is not None:
                self._device.close()
                self._device = None
        if self._device is None:
            if now < self._retry_at:
                return
            try:
                self._device = self._factory()
            except (OSError, V4L2Error) as exc:
                self._device, self.status = None, msg("vcam.status.device_error", error=str(exc))
            else:
                if self._device is None:
                    self.status = msg("vcam.status.no_device")
            if self._device is None:
                self._retry_at = now + self.RETRY_S
                return
            self.status = msg("vcam.status.running")
        frame = self.current_frame()
        try:
            self._device.write(frame)
            self.frames_written += 1
        except OSError as exc:
            log.warning("virtual camera write: %s", exc)
            self._device.close()
            self._device = None
            self._retry_at = now + self.RETRY_S
            self.status = msg("vcam.status.write_error", error=exc.strerror or str(exc))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="vcam", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._device is not None:
            self._device.close()
            self._device = None
        self.status = msg("vcam.status.off")

    def _loop(self) -> None:
        period = 1.0 / self.fps
        next_t = time.monotonic()
        while not self._stop.is_set():
            self.tick()
            next_t += period
            delay = next_t - time.monotonic()
            if delay < -1.0:
                next_t = time.monotonic()        # after a long pause we do not catch up on frames
            elif delay > 0:
                self._stop.wait(delay)
