"""Wykonawca: jedyne miejsce w silniku, które zapisuje kontrolki ruchu kamery.

* Ruch absolutny: firmware ignoruje wartość równą ostatnio zadanej, więc wtedy
  najpierw wysyłamy wartość różną o 1" (niezauważalne), potem właściwą.
* Ruch prędkościowy: wielkość wpisu nie ma znaczenia (zmierzone) - wpisujemy
  tylko znak. Nie zawracamy w locie (tilt tego nie umie) - najpierw stop.
* Strażnik: rozkaz prędkości jest ważny ``watchdog_s``. Jeśli pętla go nie
  odświeży (np. zawiesiła się), osobny wątek wysyła stop. Kamera nie może
  kręcić się sama przez zawieszony program.

Każdy rozkaz trafia też do modelu głowicy, żeby ten wiedział, co zadano.
"""

from __future__ import annotations

import threading
import time

from .director import Command
from .head_model import HeadModel, ZoomModel
from .v4l2 import (CID_PAN_ABSOLUTE, CID_PAN_SPEED, CID_TILT_ABSOLUTE,
                   CID_TILT_SPEED, CID_ZOOM_ABSOLUTE, CID_ZOOM_CONTINUOUS)

ABS_CTRL = {"pan": CID_PAN_ABSOLUTE, "tilt": CID_TILT_ABSOLUTE}
VEL_CTRL = {"pan": CID_PAN_SPEED, "tilt": CID_TILT_SPEED}
VEL_MAGNITUDE = 1
WATCHDOG_S = 0.3
WATCHDOG_PERIOD = 0.05
# Odczyt zoomu różny od ostatnio zadanego o więcej niż tyle (w spoczynku optyki) znaczy,
# że zoom zmienił ktoś inny: suwak, przyciski, preset albo inny program.
MANUAL_ZOOM_TOLERANCE = 50


class Actuator:
    def __init__(self, controls, head: HeadModel, watchdog_s: float = WATCHDOG_S) -> None:
        self.controls = controls
        self.head = head
        self.watchdog_s = watchdog_s
        self.zoom_value = 0
        self.zoom_model = ZoomModel(head.dynamics)
        self._last_abs: dict[str, int | None] = {"pan": None, "tilt": None}
        self._vel = {"pan": 0, "tilt": 0}
        self._deadline = {"pan": 0.0, "tilt": 0.0}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- stan początkowy -------------------------------------------------

    def sync_from_device(self, t: float) -> None:
        """Zatrzymuje ewentualny ruch i przyjmuje odczyt pozycji za prawdę.

        Odczyt jest dokładny po ruchu absolutnym, a na starcie zakładamy, że
        głowica stoi. Zerowanie prędkości zabija ruch pozostawiony przez inny
        program (np. dawny wpis ``PAN_SPEED=15``). Tak samo zoom ciągły: kamera
        pamięta go i jedzie optyką do oporu, a odczyt ``ZOOM_ABSOLUTE`` tego nie widzi.
        """
        with self._lock:
            self.stop_all(t)
            if self.controls.control(CID_ZOOM_CONTINUOUS) is not None:
                self.controls.set(CID_ZOOM_CONTINUOUS, 0)
            for axis, cid in ABS_CTRL.items():
                value = int(self.controls.get(cid))
                self.head.reset(axis, value)
                self._last_abs[axis] = value
            self.refresh_zoom()

    def refresh_zoom(self, t: float | None = None) -> bool:
        """Czyta zoom z kamery. Z ``t``: zwraca True, gdy wartość zmienił ktoś inny.

        W trakcie jazdy optyki (``zoom_model``) nie oceniamy - odczyt bywa wtedy
        niepewny, a różnica od wartości zadanej jest naturalna.
        """
        with self._lock:
            if t is not None and self.zoom_model.moving(t):
                return False
            value = int(self.controls.get(CID_ZOOM_ABSOLUTE))
            external = t is not None and abs(value - self.zoom_value) > MANUAL_ZOOM_TOLERANCE
            self.zoom_value = value
            self.zoom_model.reset(value)
            return external

    # --- rozkazy ------------------------------------------------------------

    def _range(self, ctrl_id: int) -> tuple[float, float]:
        c = self.controls.control(ctrl_id)
        return (c.minimum, c.maximum) if c else (float("-inf"), float("inf"))

    def move_absolute(self, axis: str, value: float, t: float) -> None:
        with self._lock:
            if self._vel[axis]:
                self._write_vel(axis, 0, t)
            cid = ABS_CTRL[axis]
            lo, hi = self._range(cid)
            target = int(round(min(max(value, lo), hi)))
            if target == self._last_abs[axis]:
                self.controls.set(cid, target - 1 if target > lo else target + 1)
            self.controls.set(cid, target)
            self._last_abs[axis] = target
            self.head.command_absolute(axis, target, t)

    def velocity(self, axis: str, direction: float, t: float) -> None:
        with self._lock:
            d = 0 if direction == 0 else (1 if direction > 0 else -1)
            if d:
                self._deadline[axis] = t + self.watchdog_s
            if d == self._vel[axis]:
                return
            if d and self._vel[axis]:
                self._write_vel(axis, 0, t)      # bez nawrotu w locie
                return
            self._write_vel(axis, d, t)

    def _write_vel(self, axis: str, direction: int, t: float) -> None:
        self.controls.set(VEL_CTRL[axis], direction * VEL_MAGNITUDE)
        self._vel[axis] = direction
        self.head.command_velocity(axis, direction, t)

    def zoom(self, value: float, t: float) -> None:
        with self._lock:
            lo, hi = self._range(CID_ZOOM_ABSOLUTE)
            self.zoom_value = int(round(min(max(value, lo), hi)))
            self.controls.set(CID_ZOOM_ABSOLUTE, self.zoom_value)
            self.zoom_model.command(self.zoom_value, t)

    def apply(self, commands: list[Command], t: float) -> None:
        with self._lock:
            for c in commands:
                if c.kind == "abs":
                    self.move_absolute(c.axis, c.value, t)
                elif c.kind == "vel":
                    self.velocity(c.axis, c.value, t)
                elif c.kind == "zoom":
                    self.zoom(c.value, t)

    def stop_all(self, t: float) -> None:
        """Zeruje prędkości obu osi - zawsze, także gdy nic nie jedzie."""
        with self._lock:
            for axis in ("pan", "tilt"):
                self.controls.set(VEL_CTRL[axis], 0)
                if self._vel[axis]:
                    self._vel[axis] = 0
                    self.head.command_velocity(axis, 0, t)

    # --- strażnik -----------------------------------------------------------

    def check_watchdog(self, t: float) -> bool:
        """Zatrzymuje osie, których rozkaz prędkości wygasł. Zwraca, czy coś zatrzymał."""
        stopped = False
        with self._lock:
            for axis in ("pan", "tilt"):
                if self._vel[axis] and t > self._deadline[axis]:
                    self._write_vel(axis, 0, t)
                    stopped = True
        return stopped

    def start_watchdog(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._watch, name="ptz-watchdog", daemon=True)
        self._thread.start()

    def stop_watchdog(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _watch(self) -> None:
        while not self._stop.wait(WATCHDOG_PERIOD):
            try:
                self.check_watchdog(time.monotonic())
            except Exception:
                pass    # błąd zapisu (np. odłączona kamera) obsłuży pętla trackera
