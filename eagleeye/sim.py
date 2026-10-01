"""Symulator kamery i sceny - do testów zamkniętej pętli i odtwarzania sesji.

``SimCamera`` udaje ControlDevice z fizyką głowicy zmierzoną w spike'u
(2026-09-22): opóźnienie i krzywa S ruchu absolutnego, rozpędzanie i wybieg
ruchu prędkościowego, odczyt zwracający pozycję zadaną, ignorowanie wpisu
równego ostatniemu i brak nawrotu tiltu w locie. "Prawdę" liczy osobny
HeadModel, który może mieć inną dynamikę niż model trackera.

``SimScene`` zamienia trajektorię głowy w kątach świata na obserwacje
w pikselach - z szumem, skokami (twarz <-> sylwetka) i zanikiem przy
rozmyciu, gdy głowica jedzie szybko.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from .core import TrackingCore
from .director import SLEDZENIE
from .framing import GOLDEN
from .geometry import View, deg
from .head_model import Dynamics, HeadModel
from .perception import Observation
from .profiles import Profile
from .v4l2 import (CID_PAN_ABSOLUTE, CID_PAN_SPEED, CID_TILT_ABSOLUTE,
                   CID_TILT_SPEED, CID_ZOOM_ABSOLUTE, Control)

FRAME_LAG = 0.05          # klatka powstaje tyle przed chwilą jej obróbki
BLUR_SPEED = deg(45)      # powyżej tej prędkości kątowej detektor nic nie widzi
_RANGES = {
    CID_PAN_ABSOLUTE: (-612000, 612000),
    CID_TILT_ABSOLUTE: (-108000, 324000),
    CID_PAN_SPEED: (-24, 24),
    CID_TILT_SPEED: (-20, 20),
    CID_ZOOM_ABSOLUTE: (0, 5680),
}
_AXIS = {CID_PAN_ABSOLUTE: "pan", CID_TILT_ABSOLUTE: "tilt",
         CID_PAN_SPEED: "pan", CID_TILT_SPEED: "tilt"}


class SimCamera:
    def __init__(self, clock: Callable[[], float], dynamics: Dynamics = Dynamics()) -> None:
        self.clock = clock
        self.truth = HeadModel(dynamics)
        self.values = {cid: 0 for cid in _RANGES}
        self.real_moves = 0          # zapisy absolutne dalej niż 0,5° od poprzedniego
        self.moves_by_axis = {"pan": 0, "tilt": 0}
        self.interrupted = 0         # ... wysłane w trakcie cudzego ruchu absolutnego
        self.vel_starts = 0          # ruszenia w trybie prędkości (z postoju)

    def place(self, pan: float, tilt: float = 0.0) -> None:
        self.truth.reset("pan", pan)
        self.truth.reset("tilt", tilt)
        self.values[CID_PAN_ABSOLUTE] = int(pan)
        self.values[CID_TILT_ABSOLUTE] = int(tilt)

    def control(self, ctrl_id: int) -> Control | None:
        if ctrl_id not in _RANGES:
            return None
        lo, hi = _RANGES[ctrl_id]
        return Control(id=ctrl_id, name=str(ctrl_id), type=1, minimum=lo, maximum=hi,
                       step=1, default=0, flags=0)

    def get(self, ctrl_id: int) -> int:
        return self.values[ctrl_id]

    def set(self, ctrl_id: int, value: int) -> int:
        t = self.clock()
        value = int(value)
        if ctrl_id in (CID_PAN_ABSOLUTE, CID_TILT_ABSOLUTE):
            axis = _AXIS[ctrl_id]
            if value != self.values[ctrl_id]:
                if abs(value - self.values[ctrl_id]) > deg(0.5):
                    self.real_moves += 1
                    self.moves_by_axis[axis] += 1
                    target = self.truth.target(axis)
                    if self.truth.moving(axis, t) and target is not None and abs(value - target) > deg(0.5):
                        self.interrupted += 1
                self.truth.command_absolute(axis, value, t)
        elif ctrl_id in (CID_PAN_SPEED, CID_TILT_SPEED):
            axis = _AXIS[ctrl_id]
            d = (value > 0) - (value < 0)
            current = self.truth.velocity_direction(axis)
            if axis == "tilt" and d and current and d != current:
                d = 0                                   # tilt nie zawraca w locie - tylko staje
            if d and not current:
                self.vel_starts += 1
            self.truth.command_velocity(axis, d, t)
        self.values[ctrl_id] = value
        return value


class SimScene:
    def __init__(self, path: Callable[[float], tuple[float, float]],
                 present: Callable[[float], bool] | None = None, noise_px: float = 3.0,
                 jump_every: int = 0, jump_px: float = 24.0,
                 frame: tuple[int, int] = (960, 540), seed: int = 1,
                 exposure_lag: float = 0.0, lag_jitter: float = 0.0,
                 yaw: Callable[[float], float | None] | None = None,
                 head_scale: Callable[[float], float] | None = None) -> None:
        self.path = path
        # Klatka powstaje o tyle wcześniej, niż mówi jej znacznik czasu (uvcvideo stempluje
        # ~koniec transmisji). W trakcie ruchu kamery daje to pomiar przesunięty w kierunku
        # jazdy - zmierzone na kamerze 3-4° (sesja 20260923-003153).
        self.exposure_lag = exposure_lag
        # Rozrzut tej zwłoki z klatki na klatkę (USB, MJPEG, rolling shutter). W bezruchu bez
        # znaczenia, w trakcie jazdy daje błąd pomiaru rzędu prędkość kamery × rozrzut -
        # na nagraniach 0,4-1° na klatkę wobec 0,04° w spoczynku (sesja 20260926-011024).
        self.lag_jitter = lag_jitter
        self.present = present or (lambda t: True)
        self.noise_px = noise_px
        self.jump_every = jump_every
        self.jump_px = jump_px
        self.frame = frame
        self.yaw = yaw
        # Skala głowy w kątach świata (arcsec) - z niej scena liczy piksele klatki.
        self.head_scale = head_scale
        self._rng = random.Random(seed)
        self._n = 0

    def head_pixel(self, t: float, camera: SimCamera, zoom: float) -> tuple[float, float] | None:
        """Prawdziwe położenie głowy w kadrze (None = poza kadrem albo nieobecna)."""
        if not self.present(t):
            return None
        view = View(*self.frame, zoom)
        x, y = view.world_to_pixel(*self.path(t), *camera.truth.angles(t))
        if 0 <= x < self.frame[0] and 0 <= y < self.frame[1]:
            return x, y
        return None

    def observe(self, t: float, camera: SimCamera, zoom: float) -> Observation | None:
        ft = t - FRAME_LAG
        lag = self.exposure_lag + (self._rng.gauss(0.0, self.lag_jitter) if self.lag_jitter else 0.0)
        point = self.head_pixel(ft - lag, camera, zoom)
        if point is None:
            return None
        a, b = camera.truth.angles(ft - 0.03), camera.truth.angles(ft)
        if math.hypot(b[0] - a[0], b[1] - a[1]) / 0.03 > BLUR_SPEED:
            return None
        self._n += 1
        x = point[0] + self._rng.gauss(0.0, self.noise_px)
        y = point[1] + self._rng.gauss(0.0, self.noise_px)
        if self.jump_every and self._n % self.jump_every == 0:
            y += self.jump_px
        scale_px = None
        if self.head_scale is not None:
            scale_px = self.head_scale(ft) / View(*self.frame, zoom).arcsec_per_px
        return Observation(x, y, ft, 0.9, "twarz", (int(x) - 20, int(y) - 20, 40, 40),
                           yaw=self.yaw(ft) if self.yaw else None, head_scale_px=scale_px)


@dataclass
class SimResult:
    duration: float
    frame: tuple[int, int]
    samples: list = field(default_factory=list)     # (t, x, y) prawdziwej głowy albo (t, None, None)
    real_moves: int = 0
    interrupted: int = 0
    vel_starts: int = 0
    found_at: float | None = None
    zoom_moves: int = 0

    def moves_per_min(self) -> float:
        return self.real_moves / (self.duration / 60.0)

    def motion_starts_per_min(self) -> float:
        """Każde ruszenie głowicy (ruch absolutny albo start jazdy) - miara szarpania.

        Widz widzi każde ruszenie i zatrzymanie, niezależnie od tego, czy rozkaz
        był przerwany. Miara bez progu: rozstrzyga odbiór na żywo (Task 15).
        """
        return (self.real_moves + self.vel_starts) / (self.duration / 60.0)

    def interrupted_per_min(self) -> float:
        return self.interrupted / (self.duration / 60.0)

    def outside_fraction(self, profile: Profile, t_from: float = 0.0) -> float:
        """Część czasu z głową poza strefą wyzwalania (nieobecność w kadrze też się liczy)."""
        w, h = self.frame
        rows = [s for s in self.samples if s[0] >= t_from]
        bad = 0
        for _, x, y in rows:
            if x is None or abs(x - w / 2) > profile.trigger_pan * w or abs(y - GOLDEN * h) > profile.trigger_tilt * h:
                bad += 1
        return bad / max(1, len(rows))

    def inside_at(self, profile: Profile, t: float) -> bool:
        w, h = self.frame
        s = min(self.samples, key=lambda r: abs(r[0] - t))
        return s[1] is not None and abs(s[1] - w / 2) <= profile.trigger_pan * w and abs(s[2] - GOLDEN * h) <= profile.trigger_tilt * h


def simulate(profile: Profile, scene: SimScene, seconds: float, *, dyn_true: Dynamics = Dynamics(),
             dyn_model: Dynamics = Dynamics(), start_pan: float = 0.0, start_tilt: float = 0.0,
             search: bool = False, home: tuple[float, float] | None = None,
             rate: float = 15.0, auto_zoom: bool = False, start_zoom: float = 0.0) -> SimResult:
    now = [0.0]
    cam = SimCamera(lambda: now[0], dyn_true)
    cam.place(start_pan, start_tilt)
    core = TrackingCore(cam, profile, dyn_model)
    core.actuator.sync_from_device(0.0)
    core.director.home = home
    core.director.auto_zoom = auto_zoom
    if start_zoom:
        cam.values[CID_ZOOM_ABSOLUTE] = int(start_zoom)
        core.actuator.refresh_zoom()
    if search:
        core.director.start_search(0.0, 0.0)
    result = SimResult(seconds, scene.frame)
    dt = 1.0 / rate
    for i in range(int(seconds * rate)):
        t = now[0] = i * dt
        obs = scene.observe(t, cam, core.actuator.zoom_value)
        cmds = core.step(t, obs, *scene.frame)
        result.zoom_moves += sum(1 for c in cmds if c.kind == "zoom")
        if result.found_at is None and obs is not None and core.director.status.mode == SLEDZENIE:
            result.found_at = t
        point = scene.head_pixel(t, cam, core.actuator.zoom_value)
        result.samples.append((t, *(point if point else (None, None))))
    result.real_moves, result.interrupted, result.vel_starts = cam.real_moves, cam.interrupted, cam.vel_starts
    result.core = core      # type: ignore[attr-defined] - do asercji w testach
    result.camera = cam     # type: ignore[attr-defined]
    return result
