"""Rdzeń śledzenia: jeden krok potoku, wspólny dla prawdziwej kamery i symulatora.

obserwacja (piksele, czas klatki) -> kąt świata (przez model głowicy w chwili
klatki) -> filtr -> reżyser -> wykonawca.
"""

from __future__ import annotations

from .actuator import Actuator
from .director import Command, Director, Limits
from .geometry import View, deg
from .head_model import Dynamics, HeadModel
from .perception import Observation
from .profiles import Profile
from .target_filter import FilterSettings, TargetFilter
from .v4l2 import CID_PAN_ABSOLUTE, CID_TILT_ABSOLUTE


def limits_from_controls(controls) -> Limits:
    def rng(cid: int, lo: float, hi: float) -> tuple[float, float]:
        c = controls.control(cid)
        return (c.minimum, c.maximum) if c else (lo, hi)

    pan = rng(CID_PAN_ABSOLUTE, -deg(170), deg(170))
    tilt = rng(CID_TILT_ABSOLUTE, -deg(30), deg(90))
    return Limits(pan[0], pan[1], tilt[0], tilt[1])


class TrackingCore:
    def __init__(self, controls, profile: Profile, dynamics: Dynamics = Dynamics(),
                 filter_settings: FilterSettings = FilterSettings(),
                 invert_pan: bool = False, invert_tilt: bool = False) -> None:
        self.head = HeadModel(dynamics)
        self.actuator = Actuator(controls, self.head)
        self.filter = TargetFilter(filter_settings)
        self.director = Director(profile, limits_from_controls(controls), dynamics)
        self.invert_pan = invert_pan
        self.invert_tilt = invert_tilt
        self.last_world: tuple[float, float] | None = None
        self.last_estimate = None
        self._hold_until = float("-inf")

    def view(self, frame_w: int, frame_h: int) -> View:
        return View(frame_w, frame_h, self.actuator.zoom_value, self.invert_pan, self.invert_tilt)

    def step(self, t: float, obs: Observation | None, frame_w: int, frame_h: int) -> list[Command]:
        view = self.view(frame_w, frame_h)
        self.last_world = None
        # Klatki z czasu ruchu absolutnego pomijamy: ich znacznik czasu jest późniejszy niż
        # naświetlenie, a model krzywej S nie jest idealny - kąt świata wychodził przesunięty
        # o 3-4° w kierunku jazdy (sesja 20260923-003153). Na czas ruchu reżyser dostaje
        # ostatnią pewną pozycję celu. Tylko w profilach z hold_during_moves (rozmowa):
        # idący cel (prezentacja) potrzebuje pomiarów także w ruchu.
        hold = self.director.profile.hold_during_moves
        zoom = self.actuator.zoom_model
        # Klatki z czasu jazdy zoomu też pomijamy (w każdym profilu): pole widzenia z kontrolki
        # nie jest wtedy prawdziwe, a błąd skaluje całą odległość punktu od środka kadru.
        if (obs is not None and not (hold and self._absolute_move(obs.t))
                and not zoom.moving(obs.t)):
            cam_pan, cam_tilt = self.head.angles(obs.t)     # gdzie patrzyła kamera w chwili klatki
            world = view.pixel_to_world(obs.x, obs.y, cam_pan, cam_tilt)
            scale = None if obs.head_scale_px is None else obs.head_scale_px * view.arcsec_per_px
            if self.filter.update(obs.t, *world, yaw=obs.yaw, head_scale=scale,
                                  cam_speed=self._cam_speed(obs.t)):
                self.last_world = world
        # Trzymamy też chwilę po dojeździe: ostatni pomiar jest sprzed całego ruchu, więc
        # bez tego cel "ginął" dokładnie w chwili dojazdu i reżyser wysyłał drugi ruch
        # (na ostatni azymut) - zgłoszone z aplikacji jako dojeżdżanie na dwa razy.
        if (hold and self._absolute_move(t)) or zoom.moving(t):
            self._hold_until = t + self.filter.settings.lost_after
        est = self.filter.estimate(t, hold=t <= self._hold_until, capped=hold)
        self.last_estimate = est
        cmds = self.director.tick(t, est, self.head, view, zoom_moving=zoom.moving(t))
        self.actuator.apply(cmds, t)
        return cmds

    def _cam_speed(self, t: float) -> tuple[float, float]:
        """Prędkość osi kamery (pan, tilt) w chwili ``t`` w ruchu absolutnym [arcsec/s].

        Tylko ruch absolutny: niepewność siedzi w krzywej S (opóźnienie, kształt - błąd modelu
        0,2-0,4° RMS, tools/measure_trajectory.py). Jazda prędkościowa ma stałą prędkość i jest
        modelowana dobrze, a podążanie potrzebuje szybkiej estymaty prędkości celu - większa
        wariancja pomiaru opóźniała ją (symulacja chodzenia: 15% vs 18% czasu poza strefą).
        """
        h = 0.02
        a, b = self.head.angles(t - h), self.head.angles(t + h)
        out = []
        for i, axis in enumerate(("pan", "tilt")):
            absolute = self.head.target(axis) is not None
            moving = self.head.moving(axis, t) or self.head.moving(axis, t - h)
            out.append(abs(b[i] - a[i]) / (2 * h) if absolute and moving else 0.0)
        return out[0], out[1]

    def _absolute_move(self, t: float) -> bool:
        return any(self.head.moving(axis, t) and self.head.target(axis) is not None
                   for axis in ("pan", "tilt"))
