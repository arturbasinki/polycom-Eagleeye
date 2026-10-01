"""Tracking profiles: "talk" (calm) and "presentation" (following).

Starting values from the specification; in the UI only the fields
in ``TUNABLE`` can be overridden (the "advanced" section).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from .framing import SHOTS
from .geometry import deg


@dataclass(frozen=True)
class Profile:
    name: str
    trigger_pan: float       # trigger zone: frame-width fraction from the framing point
    trigger_tilt: float      # ... and frame height
    dwell: float             # s continuously outside the zone before the camera moves
    lead: bool               # lead the movement by the target velocity
    follow: bool             # velocity following (pan only)
    follow_speed: float      # target speed threshold for following [arcsec/s]
    ladder_max: int          # last step of the target loss ladder
    ladder_step_time: float  # s between ladder steps
    # Measurements from frames taken during an absolute camera move are shifted
    # by 3-4° in the direction of travel. When the target stands still after the move (talk),
    # it is better to skip them and hold the last certain position; when the target walks
    # (presentation), skipping them blinds the tracker exactly when the target is moving.
    hold_during_moves: bool = False
    # Catching up with a target that vanished at the edge while moving (ladder step 1). At the
    # moment of loss the filter velocity is sometimes worthless (detection gaps) - in talk it
    # fired 54-61° too far, while the last azimuth hit the person (session 20260923-020939).
    catch_up: bool = True
    # Composition (framing.py): shot and frame side. The vertical is set by the
    # golden-ratio line (framing.GOLDEN) - shared by the profiles; the former head_height
    # (0.375 / 0.30) is removed.
    shot: str = "MCU"        # shot: framing.SHOTS
    side_enter: float = 0.35 # |yaw| above - face turned away, frame to the side point
    side_exit: float = 0.20  # |yaw| below - face straight ahead, return to centre
    side_dwell: float = 1.5  # s of a sustained turn (or return) before the side changes


# trigger_tilt = 0.12 (review 2026-09-26): the trigger zone is the reaction threshold for a
# *large* deviation, while composition accuracy is provided by the 5% band with a quiet
# re-fit (director.COMPOSITION_BAND/REFIT_DWELL). The calibration value 0.05 (≈2°) was equal
# to the band, so a vertical re-fit did not exist, and every head nod (±2°) after the 0.2 s
# dwell in presentation moved the tilt - straight onto the peak of the nod, and a second move
# brought it back (session 20260926-011024).
TALK = Profile("talk", 0.15, 0.12, 0.8, False, False, deg(8), 2, 4.0,
               hold_during_moves=True, catch_up=False, shot="MCU")
PRESENTATION = Profile("presentation", 0.26, 0.12, 0.2, True, True, deg(8), 4, 1.5, shot="MS")
PROFILES = {p.name: p for p in (TALK, PRESENTATION)}
DEFAULT_PROFILE = "talk"
TUNABLE = ("trigger_pan", "trigger_tilt", "dwell", "ladder_step_time",
           "shot", "side_enter", "side_exit", "side_dwell")


def resolve(name: str, overrides: dict | None = None) -> Profile:
    base = PROFILES.get(name, PROFILES[DEFAULT_PROFILE])
    changes: dict = {}
    for key, value in (overrides or {}).items():
        if key == "shot":
            if value in SHOTS:
                changes[key] = value
        elif key in TUNABLE:
            changes[key] = float(value)
    return dataclasses.replace(base, **changes)
