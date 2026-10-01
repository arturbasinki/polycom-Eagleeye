"""Virtual camera placeholder: the "EagleEye is not running" slate when the app is off.

Chrome sees the v4l2loopback device (exclusive_caps=1) as a camera only while
someone writes to it, and it builds its camera list once - at startup. Without the
placeholder EagleEye disappears from Meet if Chrome started before the app. The placeholder runs
from login (a systemd --user service), writes the slate a few times per second
and releases the device as soon as the app's socket answers; after the app
closes it takes it back. Receivers (Meet) do not lose the device.

    .venv/bin/python -m eagleeye.placeholder
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from typing import Callable

from .config import language_setting
from .control import instance_running
from .i18n import set_language
from .v4l2 import OutputDevice, V4L2Error
from .vcam import OUT_SIZE, card_i420, card_texts, open_loopback

log = logging.getLogger("eagleeye")

OFF_CARD = ("vcam.card.off.title", "vcam.card.off.subtitle")
WRITE_PERIOD_S = 0.2     # 5 fps is enough for a still slate
IDLE_PERIOD_S = 0.5      # how often we check whether the app is running / the device is free


class Placeholder:
    def __init__(self, device_factory: Callable[[], OutputDevice | None] = open_loopback,
                 app_running: Callable[[], bool] = instance_running,
                 size: tuple[int, int] = OUT_SIZE,
                 language: Callable[[], str] = language_setting) -> None:
        self._factory = device_factory
        self._app_running = app_running
        self._size = size
        self._language, self._card, self._card_language = language, b"", None
        self._device = None

    def tick(self) -> str:
        """One step: releases the device to the app or writes the slate. Returns the state."""
        wanted = self._language()
        if wanted != self._card_language:
            set_language(wanted)
            self._card = card_i420(*card_texts(OFF_CARD), size=self._size)
            self._card_language = wanted
        if self._app_running():
            self.release()
            return "app"
        if self._device is None:
            try:
                self._device = self._factory()
            except (OSError, V4L2Error):
                self._device = None       # taken by the app during startup, or no module
            if self._device is None:
                return "no_device"
        try:
            self._device.write(self._card)
        except OSError:
            self.release()
            return "write_error"
        return "writing"

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
                log.info("placeholder: %s", state)
                last = state
            stop.wait(WRITE_PERIOD_S if state == "writing" else IDLE_PERIOD_S)
    finally:
        placeholder.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
