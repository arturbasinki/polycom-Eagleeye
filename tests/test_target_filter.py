#!/usr/bin/env python3
"""Target filter: Kalman in world angles, jump gating, target loss.

    .venv/bin/python tests/test_target_filter.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import run  # noqa: E402

from eagleeye.geometry import deg  # noqa: E402
from eagleeye.target_filter import FilterSettings, TargetFilter  # noqa: E402

DT = 1 / 15


def test_stationary_noisy_target_converges() -> None:
    # Noise 2× the measured one (0.04° - MLE from recordings, 2026-09-26). The velocity at rest
    # must stay below the director's settle threshold (director.SETTLE_SPEED = 2°/s).
    rng = random.Random(1)
    f = TargetFilter()
    for i in range(60):
        f.update(i * DT, deg(10) + rng.gauss(0, 300), deg(-5) + rng.gauss(0, 300))
    e = f.estimate(60 * DT)
    assert abs(e.pan - deg(10)) < deg(0.3) and abs(e.tilt - deg(-5)) < deg(0.3)
    assert abs(e.v_pan) < deg(1.5) and abs(e.v_tilt) < deg(1.5)


def test_walking_target_velocity_is_estimated() -> None:
    f = TargetFilter()
    v = deg(20)
    for i in range(45):
        f.update(i * DT, v * i * DT, 0.0)
    e = f.estimate(45 * DT)
    assert abs(e.v_pan - v) < 0.1 * v


def test_prediction_extrapolates_with_velocity_but_only_briefly() -> None:
    """We predict motion briefly, but we do not drag the old velocity through detection gaps -
    that pushed the estimate 5-7° past a stopped person (session 20260923-003153)."""
    s = FilterSettings()
    f = TargetFilter(s)
    for i in range(45):
        f.update(i * DT, deg(20) * i * DT, 0.0)
    now = 44 * DT
    assert f.estimate(now + s.max_extrapolation).pan > f.estimate(now).pan + deg(1)
    assert f.estimate(now + 0.35).pan == f.estimate(now + s.max_extrapolation).pan


def test_hold_keeps_the_target_during_camera_move() -> None:
    s = FilterSettings()
    f = TargetFilter(s)
    f.update(0.0, deg(10), 0.0)
    assert f.estimate(1.5) is None
    held = f.estimate(1.5, hold=True)
    assert held is not None and abs(held.pan - deg(10)) < 1.0
    assert f.estimate(s.max_hold + 0.1, hold=True) is None


def test_single_detector_jump_is_rejected() -> None:
    f = TargetFilter()
    for i in range(30):
        f.update(i * DT, 0.0, 0.0)
    accepted = f.update(30 * DT, 49000.0, 0.0)       # ~240 px at 204"/px
    assert not accepted
    assert abs(f.estimate(30 * DT).pan) < 1000


def test_repeated_jumps_mean_the_target_really_moved() -> None:
    s = FilterSettings()
    f = TargetFilter(s)
    for i in range(30):
        f.update(i * DT, 0.0, 0.0)
    for k in range(s.reset_after_rejects):
        f.update((30 + k) * DT, deg(30), 0.0)
    assert abs(f.estimate((30 + s.reset_after_rejects) * DT).pan - deg(30)) < 2000


def test_target_is_lost_after_timeout() -> None:
    s = FilterSettings()
    f = TargetFilter(s)
    f.update(0.0, 0.0, 0.0)
    assert f.estimate(s.lost_after * 0.5) is not None
    assert f.estimate(s.lost_after + 0.01) is None


def test_reset_forgets_target() -> None:
    f = TargetFilter()
    f.update(0.0, 0.0, 0.0)
    f.reset()
    assert f.estimate(0.0) is None


def test_measurement_during_camera_motion_counts_less() -> None:
    # A frame from a camera move: world angle = head model + pixels, and the model and exposure
    # instant are uncertain - the measurement has variance ~ (camera speed × timing_sigma)².
    a, b = TargetFilter(), TargetFilter()
    for i in range(30):
        a.update(i * DT, 0.0, 0.0)
        b.update(i * DT, 0.0, 0.0)
    a.update(30 * DT, 0.0, deg(0.5))
    b.update(30 * DT, 0.0, deg(0.5), cam_speed=(0.0, deg(60)))
    ea, eb = a.estimate(30 * DT), b.estimate(30 * DT)
    assert eb.tilt < 0.3 * ea.tilt, (ea.tilt, eb.tilt)
    assert eb.pan == ea.pan


def test_moving_camera_widens_gate() -> None:
    # A 3° deviation at rest is a detector jump (rejected); at 60°/s it fits within the
    # measurement uncertainty and is accepted (with a low weight).
    a, b = TargetFilter(), TargetFilter()
    for i in range(30):
        a.update(i * DT, 0.0, 0.0)
        b.update(i * DT, 0.0, 0.0)
    assert not a.update(30 * DT, 0.0, deg(3))
    assert b.update(30 * DT, 0.0, deg(3), cam_speed=(0.0, deg(60)))


def test_yaw_and_scale_are_smoothed() -> None:
    f = TargetFilter()
    f.update(0.0, 0.0, 0.0, yaw=0.0, head_scale=deg(4))
    f.update(0.1, 0.0, 0.0, yaw=1.0, head_scale=deg(5))
    e = f.estimate(0.1)
    a = FilterSettings().attr_alpha
    assert abs(e.yaw - a) < 1e-9 and abs(e.head_scale - (deg(4) + a * deg(1))) < 1e-6


def test_missing_yaw_and_scale_keep_previous() -> None:
    f = TargetFilter()
    f.update(0.0, 0.0, 0.0, yaw=0.5, head_scale=deg(4))
    f.update(0.1, 0.0, 0.0)
    e = f.estimate(0.1)
    assert e.yaw == 0.5 and e.head_scale == deg(4)


def test_rejected_measurement_does_not_touch_yaw() -> None:
    f = TargetFilter()
    for i in range(10):
        f.update(i * DT, 0.0, 0.0, yaw=0.0)
    assert f.update(10 * DT, deg(40), 0.0, yaw=1.0) is False
    assert f.estimate(10 * DT).yaw == 0.0


if __name__ == "__main__":
    run(globals(), "Target filter")
