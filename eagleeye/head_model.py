"""Camera head model: where the camera ACTUALLY points at time t.

Reading pan/tilt from the camera returns the commanded position, and during a
velocity move it does not change at all (measured 2026-09-22). That is why we
predict the angle from the command history and the measured firmware dynamics:

* absolute move - latency, then an S-curve (Student's t profile) with duration
  `abs_base + |distance| / abs_speed`,
* velocity move - latency, linear acceleration to cruise speed, then after the
  stop command another latency and linear deceleration (coast ~7°).

The defaults are this unit's calibration measured with the
``tools/measure_dynamics.py``, ``measure_zoom.py`` and ``measure_trajectory.py``
tools; ``config.json`` can only override them (a different camera unit).
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

from .motion import s_curve

AXES = ("pan", "tilt")


@dataclass(frozen=True)
class Dynamics:
    """Head dynamics (arcsec, seconds)."""

    # Defaults = calibration of THIS unit (Polycom EagleEye IV), measured on the
    # camera. They live in code, not only in config.json: the calibration must not disappear
    # with the settings file. config.json["dynamics"] only overrides (another unit).
    # Pan, absolute and velocity move: tools/measure_dynamics.py (2026-09-23).
    abs_latency: float = 0.1666        # from write to movement
    abs_base: float = 0.4055           # constant part of the travel time
    abs_speed: float = 67.52 * 3600    # the part that depends on distance
    abs_nu: float = 3.0                # S-curve shape
    vel_speed: float = 40.67 * 3600    # cruise speed (command magnitude irrelevant)
    vel_latency: float = 0.1657
    vel_ramp: float = 0.30             # acceleration to full speed
    vel_decel: float = 0.05            # deceleration from full speed to zero
    # Zoom: tools/measure_zoom.py (2026-09-25).
    zoom_latency: float = 0.142        # from control write to optics movement
    zoom_base: float = 0.201           # constant part of the travel time
    zoom_speed: float = 3069.5         # zoom control units per second
    # Tilt, absolute move: tools/measure_trajectory.py (2026-09-26). Slower than pan -
    # a model with the pan parameters erred during travel by 1.6° RMS (tilt in instalments,
    # oscillation); with these 0.21° RMS. None = same as pan (only for another unit, deliberately).
    tilt_abs_latency: float | None = 0.10
    tilt_abs_base: float | None = 0.80
    tilt_abs_speed: float | None = 66.5 * 3600
    tilt_abs_nu: float | None = 0.7

    def abs_params(self, axis: str = "pan") -> tuple[float, float, float, float]:
        """Absolute move (latency, base time, speed, nu) of the axis."""
        pan = (self.abs_latency, self.abs_base, self.abs_speed, self.abs_nu)
        if axis != "tilt":
            return pan
        tilt = (self.tilt_abs_latency, self.tilt_abs_base, self.tilt_abs_speed, self.tilt_abs_nu)
        return tuple(p if t is None else t for p, t in zip(pan, tilt))  # type: ignore[return-value]

    def abs_latency_of(self, axis: str) -> float:
        return self.abs_params(axis)[0]

    def abs_duration(self, distance: float, axis: str = "pan") -> float:
        _, base, speed, _ = self.abs_params(axis)
        return base + abs(distance) / speed

    def coast_distance(self) -> float:
        """Distance from the stop command at full speed to a standstill."""
        return self.vel_speed * (self.vel_latency + self.vel_decel / 2.0)

    def coast_time(self) -> float:
        return self.vel_latency + self.vel_decel

    def zoom_duration(self, distance: float) -> float:
        return self.zoom_base + abs(distance) / self.zoom_speed


def dynamics_from_settings(values: dict | None) -> Dynamics:
    """``config.json["dynamics"]`` -> Dynamics; unknown keys are ignored."""
    names = {f.name for f in dataclasses.fields(Dynamics)}
    out = {}
    for k, v in (values or {}).items():
        # A missing value or junk in the file must not erase the calibration from the code.
        if k not in names or v is None:
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            continue
    return Dynamics(**out)


def velocity_displacement(dyn: Dynamics, elapsed: float, stop_after: float | None) -> float:
    """Distance (arcsec, unsigned) after ``elapsed`` s from the move command.

    ``stop_after`` - after how many seconds from the move command the stop was issued (None = moving).
    Both commands have the same latency, so we compute in "effective" time.
    """
    v_max = dyn.vel_speed
    ramp = max(1e-6, dyn.vel_ramp)
    accel = v_max / ramp
    decel = v_max / max(1e-6, dyn.vel_decel)
    tau = elapsed - dyn.vel_latency
    if tau <= 0:
        return 0.0

    def run(t: float) -> float:
        if t <= ramp:
            return 0.5 * accel * t * t
        return 0.5 * accel * ramp * ramp + v_max * (t - ramp)

    if stop_after is None or tau <= stop_after:
        return run(tau)
    ts = max(0.0, stop_after)
    v_stop = min(v_max, accel * ts)
    u = min(tau - ts, v_stop / decel)
    return run(ts) + v_stop * u - 0.5 * decel * u * u


def velocity_stop_elapsed(dyn: Dynamics, stop_after: float) -> float:
    """After how many seconds from the move command the axis stands still, if the stop was issued
    after ``stop_after``."""
    ts = max(0.0, stop_after)
    accel = dyn.vel_speed / max(1e-6, dyn.vel_ramp)
    decel = dyn.vel_speed / max(1e-6, dyn.vel_decel)
    return dyn.vel_latency + ts + min(dyn.vel_speed, accel * ts) / decel


@dataclass
class _Abs:
    t0: float
    start: float
    target: float
    duration: float


@dataclass
class _Vel:
    t0: float
    start: float
    direction: int
    t_stop: float | None = None


class HeadModel:
    """Predicts the axis angle from commands. Does not touch the hardware."""

    def __init__(self, dynamics: Dynamics = Dynamics(), pan: float = 0.0, tilt: float = 0.0) -> None:
        self.dynamics = dynamics
        self._rest = {"pan": float(pan), "tilt": float(tilt)}
        self._motion: dict[str, _Abs | _Vel | None] = {"pan": None, "tilt": None}
        self._exact = {"pan": True, "tilt": True}

    def reset(self, axis: str, angle: float) -> None:
        """Take ``angle`` as a certain, stationary axis position."""
        self._rest[axis] = float(angle)
        self._motion[axis] = None
        self._exact[axis] = True

    def command_absolute(self, axis: str, target: float, t: float) -> None:
        start = self.angle(axis, t)
        self._motion[axis] = _Abs(t, start, float(target), self.dynamics.abs_duration(target - start, axis))
        self._exact[axis] = True

    def command_velocity(self, axis: str, direction: int, t: float) -> None:
        m = self._motion[axis]
        if direction == 0:
            if isinstance(m, _Vel) and m.t_stop is None:
                m.t_stop = t
            return
        if isinstance(m, _Vel) and m.t_stop is None and m.direction == direction:
            return
        self._motion[axis] = _Vel(t, self.angle(axis, t), 1 if direction > 0 else -1)
        self._exact[axis] = False

    def angle(self, axis: str, t: float) -> float:
        m = self._motion[axis]
        if m is None:
            return self._rest[axis]
        if isinstance(m, _Abs):
            latency, _, _, nu = self.dynamics.abs_params(axis)
            fraction = (t - m.t0 - latency) / m.duration
            if fraction >= 1.0:
                return m.target
            if fraction <= 0.0:
                return m.start
            return m.start + (m.target - m.start) * s_curve(fraction, nu)
        stop_after = None if m.t_stop is None else m.t_stop - m.t0
        return m.start + m.direction * velocity_displacement(self.dynamics, t - m.t0, stop_after)

    def angles(self, t: float) -> tuple[float, float]:
        return self.angle("pan", t), self.angle("tilt", t)

    def moving(self, axis: str, t: float) -> bool:
        m = self._motion[axis]
        if m is None:
            return False
        if isinstance(m, _Abs):
            return t < m.t0 + self.dynamics.abs_latency_of(axis) + m.duration
        if m.t_stop is None:
            return True
        return t - m.t0 < velocity_stop_elapsed(self.dynamics, m.t_stop - m.t0)

    def progress(self, axis: str, t: float) -> float:
        """Progress of the absolute move 0..1 (1 = no movement or the end)."""
        m = self._motion[axis]
        if isinstance(m, _Abs):
            return min(1.0, max(0.0, (t - m.t0 - self.dynamics.abs_latency_of(axis)) / m.duration))
        if isinstance(m, _Vel) and self.moving(axis, t):
            return 0.0
        return 1.0

    def rest_angle(self, axis: str, t: float) -> float:
        """Where the axis will stop if there are no new commands from ``t`` (the move gets a
        stop at ``t``)."""
        m = self._motion[axis]
        if m is None:
            return self._rest[axis]
        if isinstance(m, _Abs):
            return m.target
        stop_after = (t - m.t0) if m.t_stop is None else (m.t_stop - m.t0)
        return m.start + m.direction * velocity_displacement(self.dynamics, math.inf, stop_after)

    def velocity_active(self, axis: str) -> bool:
        m = self._motion[axis]
        return isinstance(m, _Vel) and m.t_stop is None

    def velocity_direction(self, axis: str) -> int:
        m = self._motion[axis]
        return m.direction if isinstance(m, _Vel) and m.t_stop is None else 0

    def target(self, axis: str) -> float | None:
        m = self._motion[axis]
        return m.target if isinstance(m, _Abs) else None

    def exact(self, axis: str) -> bool:
        return self._exact[axis]


class ZoomModel:
    """When the zoom optics travel.

    The target value is known immediately, but the image changes for another
    ``zoom_latency + zoom_duration`` - frames from that time have a different field of view
    than the control says, and yield wrong world angles.
    """

    def __init__(self, dynamics: Dynamics = Dynamics(), value: float = 0.0) -> None:
        self.dynamics = dynamics
        self.value = float(value)
        self._until = float("-inf")

    def reset(self, value: float) -> None:
        """Take ``value`` as a certain, stationary position of the optics."""
        self.value = float(value)
        self._until = float("-inf")

    def command(self, target: float, t: float) -> None:
        distance = float(target) - self.value
        if abs(distance) < 1.0:
            return
        self._until = t + self.dynamics.zoom_latency + self.dynamics.zoom_duration(distance)
        self.value = float(target)

    def moving(self, t: float) -> bool:
        return t < self._until
