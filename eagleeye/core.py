"""Tracking core: one step of the pipeline, shared by the real camera and the simulator.

observation (pixels, frame time) -> world angle (through the head model at the frame
time) -> filter -> director -> actuator.
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
        # We skip frames from an absolute move: their timestamp is later than the
        # exposure, and the S-curve model is not perfect - the world angle came out
        # shifted by 3-4° in the direction of travel (session 20260923-003153). During the
        # move the director gets the last certain target position. Only in profiles with
        # hold_during_moves (talk): a walking target (presentation) needs measurements in
        # motion too.
        hold = self.director.profile.hold_during_moves
        zoom = self.actuator.zoom_model
        # We also skip frames from a zoom move (in every profile): the field of view from the
        # control is not true then, and the error scales the whole distance of the point from the
        # frame centre.
        if (obs is not None and not (hold and self._absolute_move(obs.t))
                and not zoom.moving(obs.t)):
            cam_pan, cam_tilt = self.head.angles(obs.t)     # where the camera looked at frame time
            world = view.pixel_to_world(obs.x, obs.y, cam_pan, cam_tilt)
            scale = None if obs.head_scale_px is None else obs.head_scale_px * view.arcsec_per_px
            if self.filter.update(obs.t, *world, yaw=obs.yaw, head_scale=scale,
                                  cam_speed=self._cam_speed(obs.t)):
                self.last_world = world
        # We also hold for a moment after arrival: the last measurement is from before the
        # whole move, so without this the target "vanished" exactly at the moment of arrival
        # and the director sent a second move (to the last azimuth) - reported from the app as
        # arriving in two goes.
        if (hold and self._absolute_move(t)) or zoom.moving(t):
            self._hold_until = t + self.filter.settings.lost_after
        est = self.filter.estimate(t, hold=t <= self._hold_until, capped=hold)
        self.last_estimate = est
        cmds = self.director.tick(t, est, self.head, view, zoom_moving=zoom.moving(t))
        self.actuator.apply(cmds, t)
        return cmds

    def _cam_speed(self, t: float) -> tuple[float, float]:
        """Camera axis speed (pan, tilt) at time ``t`` during an absolute move [arcsec/s].

        Absolute moves only: the uncertainty sits in the S-curve (latency, shape - model error
        0.2-0.4° RMS, tools/measure_trajectory.py). A velocity move has constant speed and is
        modelled well, while following needs a quick target speed estimate - a larger
        measurement variance delayed it (walking simulation: 15% vs 18% of the time outside the
        zone).
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
