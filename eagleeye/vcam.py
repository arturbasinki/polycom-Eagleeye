"""Wirtualna kamera "EagleEye": obraz aplikacji jako kamera dla Meet, Teams i OBS.

Urządzenie daje moduł v4l2loopback (instalator: card_label="EagleEye",
exclusive_caps=1). Zapisujemy surowe klatki I420 (YU12) 1280x720 w stałym
tempie 30 fps - odbiorcy widzą równy strumień niezależnie od przestojów kamery.
Gdy obrazu nie ma (prywatność, kamera odłączona), wysyłamy planszę.
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

from .v4l2 import OutputDevice, V4L2Error, find_device_by_card

log = logging.getLogger("eagleeye")

CARD_LABEL = "EagleEye"
OUT_SIZE = (1280, 720)
OUT_FPS = 30.0
FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
CARD_BG_RGB = (18, 22, 28)
PRIVACY_TEXT = ("Kamera wstrzymana", "prywatność włączona")
NO_SIGNAL_TEXT = ("Brak sygnału z kamery", "sprawdź połączenie kamery z komputerem")


def i420_size(size: tuple[int, int]) -> int:
    w, h = size
    return w * h * 3 // 2


def bgr_to_i420(bgr: np.ndarray) -> bytes:
    """BGR (h, w, 3) -> I420: płaszczyzna Y, potem U i V w ćwiartce rozdzielczości.

    Pełne zakresy (Y 0-255) - tak odbierają Meet i OBS. ``COLOR_BGR2YUV_I420``
    w OpenCV 5.0 daje luma w zakresie ograniczonym (16-235), więc płaszczyzny
    pakujemy sami. Współczynniki BT.601 (``YCrCb``, jak w JPEG), nie ``BGR2YUV``
    - to analogowe YUV (U 0.492, V 0.877), które przesycało czerwienie o 23%.
    """
    y, cr, cb = cv2.split(cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb))
    h, w = bgr.shape[:2]
    u = cv2.resize(cb, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    v = cv2.resize(cr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    return b"".join((y.tobytes(), u.tobytes(), v.tobytes()))


def jpeg_to_i420(jpg: bytes, size: tuple[int, int] = OUT_SIZE) -> bytes | None:
    """Klatka MJPEG -> I420 bez przechodzenia przez RGB.

    JPEG przechowuje obraz jako YCbCr w pełnym zakresie (JFIF), czyli dokładnie
    to, czego chce wyjście - dekodujemy więc wprost do YCbCr zamiast
    YCbCr -> RGB -> YUV. Zmierzone na klatce 1080p: 26 ms CPU zamiast 67 ms.
    Pillow, nie ``cv2.imdecode`` - powód w :func:`decode_mjpeg`.
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
    u = cv2.resize(u, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    v = cv2.resize(v, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    return b"".join((y.tobytes(), u.tobytes(), v.tobytes()))


def _font(path: Path, px: int):
    try:
        return ImageFont.truetype(str(path), px)
    except OSError:
        return ImageFont.load_default()


def render_card(title: str, subtitle: str = "", size: tuple[int, int] = OUT_SIZE) -> np.ndarray:
    """Plansza: ciemne tło, wyśrodkowany tytuł i podtytuł. Pillow, bo czcionki OpenCV
    nie mają polskich znaków. Zwraca obraz BGR."""
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
    """Otwiera urządzenie "EagleEye" jako wyjście; None, gdy modułu/urządzenia nie ma."""
    path = find_device_by_card(card)
    return OutputDevice(path, size).open() if path else None


class VirtualCamera:
    """Wątek zapisujący w stałym tempie bieżącą klatkę wyjściową.

    Klatka wyjściowa: plansza prywatności, ostatnia klatka z kamery (powtarzana,
    dopóki nie przyjdzie nowa) albo plansza "brak sygnału", gdy nowej klatki nie
    było dłużej niż ``STALE_S``. Brak urządzenia albo błąd zapisu nie przerywa
    pracy - kolejna próba po ``RETRY_S``.
    """

    RETRY_S = 1.0         # także przejęcie urządzenia od zaślepki przy starcie
    STALE_S = 1.0

    def __init__(self, device_factory: Callable[[], OutputDevice | None] = open_loopback,
                 size: tuple[int, int] = OUT_SIZE, fps: float = OUT_FPS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._factory = device_factory
        self.size = (int(size[0]), int(size[1]))
        self.fps = fps
        self._clock = clock
        self._source = None
        self._last_id = 0
        self._live: bytes | None = None
        self._live_at = -math.inf
        self._privacy = False
        self._card_privacy = card_i420(*PRIVACY_TEXT, size=self.size)
        self._card_no_signal = card_i420(*NO_SIGNAL_TEXT, size=self.size)
        self._device = None
        self._retry_at = -math.inf
        self.status = "wyłączona"
        self.frames_written = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def set_source(self, stream) -> None:
        with self._lock:
            self._source = stream
            self._last_id = 0
            self._live = None

    def set_privacy(self, on: bool) -> None:
        self._privacy = bool(on)

    @property
    def privacy(self) -> bool:
        return self._privacy

    def current_frame(self) -> bytes:
        if self._privacy:
            return self._card_privacy
        with self._lock:
            source = self._source
            if source is not None:
                frame_id, jpg, _ = source.frame_timed(self._last_id, timeout=0.0)
                if jpg is not None and frame_id != self._last_id:
                    data = jpeg_to_i420(jpg, self.size)
                    if data is not None:
                        self._last_id, self._live, self._live_at = frame_id, data, self._clock()
            live, live_at = self._live, self._live_at
        if live is None or self._clock() - live_at > self.STALE_S:
            return self._card_no_signal
        return live

    def tick(self) -> None:
        """Jeden zapis: w razie potrzeby otwiera urządzenie i wysyła bieżącą klatkę."""
        now = self._clock()
        if self._device is None:
            if now < self._retry_at:
                return
            try:
                self._device = self._factory()
            except (OSError, V4L2Error) as exc:
                self._device, self.status = None, f"błąd urządzenia: {exc}"
            else:
                if self._device is None:
                    self.status = "brak urządzenia - uruchom install.sh"
            if self._device is None:
                self._retry_at = now + self.RETRY_S
                return
            self.status = "działa"
        frame = self.current_frame()
        try:
            self._device.write(frame)
            self.frames_written += 1
        except OSError as exc:
            log.warning("zapis wirtualnej kamery: %s", exc)
            self._device.close()
            self._device = None
            self._retry_at = now + self.RETRY_S
            self.status = f"błąd zapisu: {exc.strerror or exc}"

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
        self.status = "wyłączona"

    def _loop(self) -> None:
        period = 1.0 / self.fps
        next_t = time.monotonic()
        while not self._stop.is_set():
            self.tick()
            next_t += period
            delay = next_t - time.monotonic()
            if delay < -1.0:
                next_t = time.monotonic()        # po długim przestoju nie nadrabiamy klatek
            elif delay > 0:
                self._stop.wait(delay)
