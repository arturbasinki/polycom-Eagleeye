"""Target filter: the target head position and velocity in world angles.

Two independent Kalman filters (pan, tilt) with a constant-velocity model.
The world angle does not change when the camera turns, so measurements taken
while the head moves are just as good as when it is still - provided the head
position at the frame time comes from the head model.

Gating replaces the former ``max_target_jump_px``: a measurement further than
``gate_sigmas`` standard deviations from the prediction is rejected (the detector covers
the whole body at one moment and part of it at another). A few such measurements in a
row mean the target really is elsewhere - then the filter restarts.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import deg


@dataclass(frozen=True)
class FilterSettings:
    # Measurement noise and human motion model: maximum-likelihood estimate from the filter
    # innovations over 158k measurements from 9 sessions (camera-still segments, 2026-09-26). The old
    # 0.22° / 1°/s² values made the filter ~15x too sluggish: it lagged at the start of a move
    # and overshot after stopping (estimate 2-5° behind a stationary person) - the director arrived
    # in steps and came back. The filter must tell the truth about the target; whether the camera
    # should react is decided by the director (zone, dwell, composition band, target settling).
    meas_sigma: float = 300.0          # head point noise: 2x MLE (0.04°) - headroom for poor lighting
    accel_sigma: float = deg(12.0)     # how abruptly a person changes horizontal speed [arcsec/s²]
    accel_sigma_tilt: float = deg(6.0) # ... and vertically
    gate_sigmas: float = 12.0
    reset_after_rejects: int = 5
    # ... or when this much time has passed since the last accepted measurement while measurements
    # still arrive (rejected). It must be shorter than lost_after - otherwise with slower detection
    # (5 frames at 10 Hz = 0.5 s) the target "vanished" although it was visible, and the director
    # started the loss ladder instead of moving to the new position.
    reset_after_s: float = 0.25
    lost_after: float = 0.4            # s without an accepted measurement = target lost
    # Prediction beyond the last measurement by at most this much. Longer extrapolation of the old
    # velocity through detection gaps (blur while the camera moves) pushed the
    # estimate 5-7° behind a stationary person and the camera arrived with a second move.
    max_extrapolation: float = 0.1
    # When measurements are deliberately paused (absolute camera move), the estimate holds the
    # last position for at most this many seconds, instead of treating the target as lost.
    max_hold: float = 3.0
    attr_alpha: float = 0.3            # smoothing of yaw and head scale (exponential average)
    # Measurement from a frame taken while the camera moves: world angle = head angle from the model
    # at the frame time + the pixel offset. The uncertainty of the exposure time (USB, MJPEG,
    # rolling shutter) and the trajectory model error give an error ~ camera speed x timing_sigma
    # + motion_model_sigma. Instead of trusting such frames as static ones (positive feedback:
    # the measurement runs away in the direction of travel, the director adds movement -
    # oscillation in session 20260926-011024)
    # or discarding them, the filter gets their true variance (R dependent on motion).
    timing_sigma: float = 0.02         # s - from recordings: scatter in motion vs camera speed
    motion_model_sigma: float = deg(0.3)  # RMS error of the trajectory model (tools/measure_trajectory.py)


class Kalman1D:
    """Constant-velocity model: state (x, v), measurement x."""

    def __init__(self, meas_sigma: float, accel_sigma: float) -> None:
        self.r = meas_sigma ** 2
        self.q = accel_sigma ** 2
        self.x = 0.0
        self.v = 0.0
        self.p = [[0.0, 0.0], [0.0, 0.0]]
        self.t = 0.0

    def reset(self, z: float, t: float) -> None:
        self.x, self.v, self.t = float(z), 0.0, t
        self.p = [[self.r, 0.0], [0.0, deg(30.0) ** 2]]

    def _predicted(self, t: float) -> tuple[float, list[list[float]]]:
        dt = max(0.0, t - self.t)
        (p00, p01), (p10, p11) = self.p
        q = self.q
        n00 = p00 + dt * (p10 + p01) + dt * dt * p11 + q * dt ** 4 / 4.0
        n01 = p01 + dt * p11 + q * dt ** 3 / 2.0
        n10 = p10 + dt * p11 + q * dt ** 3 / 2.0
        n11 = p11 + q * dt * dt
        return self.x + self.v * dt, [[n00, n01], [n10, n11]]

    def innovation(self, z: float, t: float, r_extra: float = 0.0) -> tuple[float, float]:
        """(residual, residual variance) of the measurement ``z`` at time ``t``."""
        x, p = self._predicted(t)
        return z - x, p[0][0] + self.r + r_extra

    def update(self, z: float, t: float, r_extra: float = 0.0) -> None:
        """``r_extra`` - extra variance of this measurement (e.g. a frame from camera motion)."""
        x, p = self._predicted(t)
        s = p[0][0] + self.r + r_extra
        k0, k1 = p[0][0] / s, p[1][0] / s
        y = z - x
        self.x = x + k0 * y
        self.v = self.v + k1 * y
        self.p = [[(1 - k0) * p[0][0], (1 - k0) * p[0][1]],
                  [p[1][0] - k1 * p[0][0], p[1][1] - k1 * p[0][1]]]
        self.t = max(self.t, t)

    def position_at(self, t: float) -> float:
        return self.x + self.v * max(0.0, t - self.t)


@dataclass(frozen=True)
class TargetEstimate:
    pan: float
    tilt: float
    v_pan: float
    v_tilt: float
    t: float            # the instant the prediction is for
    last_seen: float    # the instant of the last accepted measurement
    yaw: float | None = None          # face direction, smoothed (framing.SideSelector)
    head_scale: float | None = None   # eye→shoulder segment in arcsec of world angle, smoothed

    @property
    def age(self) -> float:
        return self.t - self.last_seen


def _smooth(old: float | None, new: float | None, alpha: float) -> float | None:
    if new is None:
        return old
    if old is None:
        return float(new)
    return old + alpha * (float(new) - old)


class TargetFilter:
    def __init__(self, settings: FilterSettings = FilterSettings()) -> None:
        self.settings = settings
        self._pan = Kalman1D(settings.meas_sigma, settings.accel_sigma)
        self._tilt = Kalman1D(settings.meas_sigma, settings.accel_sigma_tilt)
        self._last_seen: float | None = None
        self._rejects = 0
        self._yaw: float | None = None
        self._scale: float | None = None

    def reset(self) -> None:
        self._last_seen = None
        self._rejects = 0
        self._yaw = None
        self._scale = None

    def _restart(self, t: float, pan: float, tilt: float) -> None:
        self._pan.reset(pan, t)
        self._tilt.reset(tilt, t)
        self._last_seen = t
        self._rejects = 0

    def motion_variance(self, cam_speed: float) -> float:
        """Extra measurement variance from a frame, when the camera axis moved with
        ``cam_speed`` [arcsec/s]."""
        if cam_speed <= 0.0:
            return 0.0
        s = self.settings
        return (cam_speed * s.timing_sigma) ** 2 + s.motion_model_sigma ** 2

    def update(self, t: float, pan: float, tilt: float,
               yaw: float | None = None, head_scale: float | None = None,
               cam_speed: tuple[float, float] = (0.0, 0.0)) -> bool:
        """Add a world-angle head measurement (and optionally yaw, scale). Returns whether it was accepted.

        ``cam_speed`` - the camera axis speed (pan, tilt) at the frame time; in motion the measurement is
        less certain (:meth:`motion_variance`) and moves the estimate less.
        """
        r_pan, r_tilt = (self.motion_variance(abs(v)) for v in cam_speed)
        if self._last_seen is None:
            self._restart(t, pan, tilt)
            self._yaw, self._scale = yaw, head_scale
            return True
        rp, sp = self._pan.innovation(pan, t, r_pan)
        rt, st = self._tilt.innovation(tilt, t, r_tilt)
        if rp * rp / sp + rt * rt / st > self.settings.gate_sigmas ** 2:
            self._rejects += 1
            if (self._rejects < self.settings.reset_after_rejects
                    and t - self._last_seen < self.settings.reset_after_s):
                return False
            self._restart(t, pan, tilt)
            self._yaw, self._scale = yaw, head_scale
            return True
        self._rejects = 0
        self._pan.update(pan, t, r_pan)
        self._tilt.update(tilt, t, r_tilt)
        self._last_seen = max(self._last_seen, t)
        a = self.settings.attr_alpha
        self._yaw = _smooth(self._yaw, yaw, a)
        self._scale = _smooth(self._scale, head_scale, a)
        return True

    def estimate(self, t: float, hold: bool = False, capped: bool = True) -> TargetEstimate | None:
        """Estimate for the instant ``t``.

        ``hold=True`` - measurements are paused because of camera motion, so no new
        measurements do not mean the target is lost (up to ``max_hold`` s).
        ``capped=False`` - prediction without the ``max_extrapolation`` limit (a walking target:
        following and catching up need prediction through detection gaps).
        """
        if self._last_seen is None:
            return None
        age = t - self._last_seen
        limit = self.settings.max_hold if hold else self.settings.lost_after
        if age > limit:
            return None
        te = min(t, self._last_seen + self.settings.max_extrapolation) if capped else t
        return TargetEstimate(self._pan.position_at(te), self._tilt.position_at(te),
                              self._pan.v, self._tilt.v, t, self._last_seen,
                              yaw=self._yaw, head_scale=self._scale)
