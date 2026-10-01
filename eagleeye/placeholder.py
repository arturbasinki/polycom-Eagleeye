"""Zaślepka wirtualnej kamery: plansza „EagleEye nie działa”, gdy aplikacja jest wyłączona.

Chrome widzi urządzenie v4l2loopback (exclusive_caps=1) jako kamerę tylko wtedy,
gdy ktoś do niego pisze, a listę kamer buduje raz - przy starcie. Bez zaślepki
EagleEye znika z Meet, jeśli Chrome wystartował przed aplikacją. Zaślepka działa
od zalogowania (usługa systemd --user), pisze planszę kilka razy na sekundę
i oddaje urządzenie, gdy tylko odpowie gniazdo aplikacji; po zamknięciu
aplikacji przejmuje je z powrotem. Odbiorcy (Meet) nie tracą urządzenia.

    .venv/bin/python -m eagleeye.placeholder
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from typing import Callable

from .control import instance_running
from .v4l2 import OutputDevice, V4L2Error
from .vcam import OUT_SIZE, card_i420, open_loopback

log = logging.getLogger("eagleeye")

OFF_TEXT = ("EagleEye nie działa", "uruchom aplikację EagleEye z menu")
WRITE_PERIOD_S = 0.2     # 5 fps wystarczy na nieruchomą planszę
IDLE_PERIOD_S = 0.5      # co tyle sprawdzamy, czy aplikacja działa / urządzenie jest wolne


class Placeholder:
    def __init__(self, device_factory: Callable[[], OutputDevice | None] = open_loopback,
                 app_running: Callable[[], bool] = instance_running,
                 size: tuple[int, int] = OUT_SIZE) -> None:
        self._factory = device_factory
        self._app_running = app_running
        self._card = card_i420(*OFF_TEXT, size=size)
        self._device = None

    def tick(self) -> str:
        """Jeden krok: oddaje urządzenie aplikacji albo pisze planszę. Zwraca stan."""
        if self._app_running():
            self.release()
            return "aplikacja"
        if self._device is None:
            try:
                self._device = self._factory()
            except (OSError, V4L2Error):
                self._device = None       # zajęte przez aplikację w trakcie startu albo brak modułu
            if self._device is None:
                return "brak urządzenia"
        try:
            self._device.write(self._card)
        except OSError:
            self.release()
            return "błąd zapisu"
        return "zapis"

    def release(self) -> None:
        if self._device is not None:
            self._device.close()
            self._device = None


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    placeholder, last = Placeholder(), None
    try:
        while not stop.is_set():
            state = placeholder.tick()
            if state != last:
                log.info("zaślepka: %s", state)
                last = state
            stop.wait(WRITE_PERIOD_S if state == "zapis" else IDLE_PERIOD_S)
    finally:
        placeholder.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
