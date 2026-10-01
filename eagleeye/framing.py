"""Frame composition: golden-ratio line, side dependent on face direction, and shot.

Pure functions without hardware. The director asks them *where* the camera
should look; *when* to move it decides itself (hysteresis, dwell).

* The head point lands on the upper golden-ratio line (y = 0.382 from the top).
* Horizontally: face straight ahead - centre; face turned to the side - the point on the opposite
  side, so the free space is in front of the face (looking room). The side changes
  only after a sustained head turn, with hysteresis (:class:`SideSelector`).
* The shot (CU / MCU / MS) says how much of the frame height the eye→shoulder segment
  should occupy; the zoom follows from it (:func:`zoom_goal`). Shot selection
  (:func:`shot_for`) is the extension point for a future "smart framing".
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .geometry import View, zoom_value_for
from .target_filter import TargetEstimate

GOLDEN = 0.382
# Fraction of the frame height for the eye→shoulder segment. The eye line sits at 0.382, and the
# bottom edge is k such segments lower: 0.382 + k·d = 1. CU k≈1.1 (shoulders), MCU k≈1.8
# (half frame), MS k≈3.2 (band).
# MCU = 0.36: calibration 2026-09-25 — at 0.34 the bottom edge landed on the solar
# plexus; +0.02 gives half the chest.
SHOTS = {"CU": 0.56, "MCU": 0.36, "MS": 0.19}
AUTO_ZOOM_MAX = 4800.0      # above 5000 the zoom curve is uncertain and detection weakens
CENTER, LEFT, RIGHT = "center", "left", "right"
SIDE_X = {CENTER: 0.5, LEFT: GOLDEN, RIGHT: 1.0 - GOLDEN}


@dataclass(frozen=True)
class Shot:
    name: str
    fraction: float         # fraction of the frame height for the eye→shoulder segment


def shot_for(profile, est: TargetEstimate | None = None) -> Shot:
    """Shot policy. Today: shot from the profile (``profile.shot``). ``est`` - for the future
    (shot chosen to match the situation: sitting / standing / walking)."""
    name = profile.shot if profile.shot in SHOTS else "MCU"
    return Shot(name, SHOTS[name])


def aim(est: TargetEstimate, side: str, view: View) -> tuple[float, float]:
    """Camera angles (pan, tilt) at which the head ``est`` is at the point of side ``side``.

    Field of view and axis signs from ``view`` - pass the view with the *target* zoom if zoom
    is moving. The point is computed in the image, so inverted axes change nothing.
    """
    sp = -1.0 if view.invert_pan else 1.0
    st = -1.0 if view.invert_tilt else 1.0
    return (est.pan - sp * (SIDE_X[side] - 0.5) * view.hfov,
            est.tilt - st * (0.5 - GOLDEN) * view.vfov)


def zoom_goal(est: TargetEstimate, shot: Shot, view: View,
              lo: float = 0.0, hi: float = AUTO_ZOOM_MAX) -> float | None:
    """Zoom value at which the head scale occupies ``shot.fraction`` of the frame height.

    The scale is in world angles, so the result does not depend on the current zoom. Without
    scale - None.
    """
    if not est.head_scale:
        return None
    wide = replace(view, zoom_value=0.0)
    factor = wide.vfov / (est.head_scale / shot.fraction)
    return min(max(zoom_value_for(factor), lo), hi)


class SideSelector:
    """Frame side: center / left / right - with dwell and hysteresis.

    * center -> side: ``|yaw| > enter`` continuously for ``dwell`` s,
    * side -> center: ``|yaw| < exit_`` for ``dwell`` s,
    * left <-> right directly, after ``dwell`` s of a sustained turn (a brief glance over the
      shoulder does not flip the frame; center only after a sustained face straight ahead),
    * ``yaw > 0`` (nose to the right in the image) -> face at the LEFT point - free space in
      front of it,
    * ``yaw is None`` (nose not visible) - no change.
    """

    def __init__(self) -> None:
        self.side = CENTER
        self._candidate: str | None = None
        self._since = 0.0

    def reset(self) -> None:
        self.side, self._candidate = CENTER, None

    @property
    def pending(self) -> str | None:
        """The side the selector is currently deliberating (dwell in progress), or None."""
        return self._candidate

    def update(self, t: float, yaw: float | None, enter: float, exit_: float, dwell: float) -> str:
        if yaw is None:
            self._candidate = None
            return self.side
        wanted = self._wanted(yaw, enter, exit_)
        if wanted == self.side:
            self._candidate = None
            return self.side
        if wanted != self._candidate:
            self._candidate, self._since = wanted, t
        if t - self._since >= dwell:
            self.side, self._candidate = wanted, None
        return self.side

    def _wanted(self, yaw: float, enter: float, exit_: float) -> str:
        facing = LEFT if yaw > 0 else RIGHT
        if self.side == CENTER:
            return facing if abs(yaw) > enter else CENTER
        if abs(yaw) < exit_:
            return CENTER
        if abs(yaw) > enter and facing != self.side:
            # Straight to the opposite side. Going "through the center" (spec before 2026-09-26)
            # gave two camera moves - to the center and only then to the other point. The
            # dwell protects against a glance over the shoulder: the new side must last ``dwell``.
            return facing
        return self.side
